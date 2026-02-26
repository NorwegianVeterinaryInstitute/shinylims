import logging
import os
import paramiko
import scp
import socket


def _ensure_remote_present_file_via_sftp( transport: paramiko.Transport, remote_absolute_file_path: str ) -> None:
    """
    Ensure the remote run directory exists using an already-authenticated SFTP session.

    Checks for the existence of the target directory on the remote host and creates it
    if missing. Aborts if the directory already exists or if creation fails.

    Raises:
        SSHException: if the directory already exists, if the transport is inactive,
        or if remote creation fails due to permission, missing parent, or other
        remote filesystem errors.
    """

    ip, port = transport.getpeername( )

    if not os.path.isabs( remote_absolute_dir_path ):
        message = f"Remote directory is not in absolute path: {remote_absolute_dir_path}"
        raise RuntimeError( message )

    if not transport.is_active( ):
        message = f"TransportError: transport not active at hop {ip}"
        demuxLogger.critical( message )
        raise SSHException( message )

    try:
        sftp_client: paramiko.SFTPClient = paramiko.SFTPClient.from_transport( transport )
    except Exception as error:
        message = f"SFTPError: failed to create SFTP session at hop {ip}:{port}"
        demuxLogger.critical( message )
        raise SSHException( message ) from error

    try:
        attributes: paramiko.SFTPAttributes | None = None
        try:
            attributes = sftp_client.stat( remote_absolute_dir_path )
        except FileNotFoundError:
            pass
        except OSError as error:
            message = f"SFTPError: stat failed for {ip}:{port}:{remote_absolute_dir_path}: {error}"
            demuxLogger.critical( message )
            raise SSHException( message ) from error

        if attributes is not None:
            if stat.S_ISDIR( attributes.st_mode ):
                message = f"{ip}:{remote_absolute_dir_path} already exists.\n"
                message += "Is this a repeat upload? If yes, delete/move the existing remote directory and try again."
                demuxLogger.critical( message )
                raise SSHException( message )
            raise SSHException( f"{ip}:{remote_absolute_dir_path} exists but is not a directory." )

        try:
            sftp_client.mkdir( remote_absolute_dir_path )
        except OSError as error:
            message = f"Directory creation error: cannot create {ip}:{port}:{remote_absolute_dir_path}. "
            message += f"SFTPError: {error}"
            demuxLogger.critical( message )
            raise SSHException( message ) from error

        demuxLogger.info( termcolor.colored( "Remote directory does not exist, created\n", color="cyan", attrs=["bold"] ) )
    finally:
        try:
            sftp_client.close( )
        except Exception:
            pass


def _authenticate_transport( hop:str, transport:paramiko.Transport, username:str, password:str, totp:str  ) -> None:
    """
    Authenticate an existing SSH transport using keyboard-interactive 2FA 
    (paramiko considers this "keyboard-interactive" even if there is not a real user typing)

    Needs username, password and TOTP credentials and performs interactive
    authentication on the provided transport. 

    Raises:
        AuthenticationException: if 2FA authentication fails or the transport
        remains unauthenticated after the interactive exchange.
    """
    hostname:str = hop
    port:int     = 22

    def _kbdint_handler( title, instructions, prompt_list ):
        responses = [ ]
        for prompt_text, echo in prompt_list:
            prompt_lower = prompt_text.lower( )
            if  ( "One-time password".lower( ) in prompt_lower ) or ( "totp" in prompt_lower ) or ( "token" in prompt_lower ) or ( "verification" in prompt_lower ) or ( "code" in prompt_lower ) :
                responses.append( totp )
            elif "password" in prompt_lower:
                responses.append( password )
            else:
                responses.append( "" )
        return responses

    transport.auth_interactive( username = username, handler = _kbdint_handler )

    if not transport.is_authenticated( ):
        message = f"AuthenticationException: SSH 2FA authentication failed for {username}@{hostname}:{port} ."
        logger.critical( message )
        # treat any raised AuthenticationException from auth_interactive() as failure
        # no other reliable signal exists that NIRD changed the TOTP token prompt
        raise AuthenticationException( message )


def _validate_hostkey( hop:str, transport:paramiko.Transport, *, port:int = 22, timeout:float = 30 ):
    """
    Validate the remote server host key for an already-created SSH Transport.

    Performs strict known_hosts verification (RejectPolicy semantics) without opening
    or authenticating the transport.
    Looks up host keys by hostname and by [host]:port for non-22 ports.

    Raise:
        RuntimeError if the host key is missing or does not exactly match; no
        accepting any non-known ssh keys, that is the job of the infra team to
        deal with
    """

    hostname = hop

    # Validate host key against known_hosts (RejectPolicy equivalent)
    host_keys = paramiko.HostKeys( )
    known_hosts_path = os.path.abspath( os.path.expanduser( constants.USER_SSH_KNOWN_HOSTS_PATH ) )
    if os.path.exists( known_hosts_path ):
        host_keys.load( known_hosts_path )

    remote_key = transport.get_remote_server_key( )

    host_key_entry = host_keys.lookup( hostname )

    if host_key_entry is None:
        message = f"RuntimeError: Host key for {hostname}:{port} not found in {known_hosts_path}. Refusing connection."
        demuxLogger.critical( message )
        raise RuntimeError( message )

    accepted = False
    for key_type, known_key in host_key_entry.items( ):
        if ( key_type == remote_key.get_name( ) ) and ( known_key == remote_key ):
            accepted = True
            break

    if not accepted:
        message = f"RuntimeError: Host key mismatch for {hostname}:{port}. Refusing connection."
        demuxLogger.critical( message )
        raise RuntimeError( message ) # https://github.com/NorwegianVeterinaryInstitute/DemultiplexRawSequenceData/issues/150


def _connect( hop: str, *, port: int = 22, timeout: float = 30.0, keepalive: int = 30 ) -> paramiko.Transport:
    """
    Build a new SSH Transport for a single hop by opening a direct TCP connection (

    The returned Transport has completed the SSH client handshake but is not
    authenticated.

    Args:
        hop: login.saga.sigma2.no
        transport: Existing Transport to tunnel through, or None for the first hop.
        port: SSH port for the hop (default: 22).
        timeout: Socket and SSH handshake timeout in seconds.

    Returns:
        An initialized but unauthenticated Paramiko Transport for the hop.

    Raises:
        socket.error: If the TCP connection fails on the hop.
        RuntimeError: If the TCP connection fails or if opening the ProxyJump
        channel fails for the hop.
    """

    transport: paramiko.Transport = None
    hostname: str = hop

    tcp_socket: socket.socket = socket.create_connection( ( hostname, port ), timeout = timeout )
    transport = paramiko.Transport( tcp_socket )

    # check if transport exists and is open
    if transport is None:
        raise RuntimeError( f"Transport creation failed at {hostname}" )
    transport.set_keepalive( keepalive )
    transport.start_client( timeout = timeout ) # Perform SSH handshake on the new transport
    if not transport.is_active( ):
        raise RuntimeError( f"SSH transport inactive after handshake at {hostname}" )

    return transport