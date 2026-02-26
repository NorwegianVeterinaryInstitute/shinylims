#

import hashlib
import logging
import os
import paramiko
import scp
import shlex
import shutil
import socket
import sys
import threading

from typing               import IO  # generic file-like


def progress(filename, size, sent) -> None:
    """
    Progress callback for SCP transfers.

    Args:
        filename: Name of the file being transferred.
        size: Total file size in bytes.
        sent: Bytes sent so far.

    Prints percentage completion to stdout.
    """
    sys.stdout.write("%s progress: %.2f%%   \r" % ( filename, float( sent )/float( size )*100 ) )


def _resolve_hostname(ip_address: str) -> str:
    """
    Resolve an IP address to a hostname once and cache the result
    for the lifetime of the process.

    Args:
        ip_address: IPv4 or IPv6 address string.

    Returns:
        Hostname from reverse DNS, or the original IP if lookup fails.
    """
    if not hasattr( _resolve_hostname, "cache" ):
        _resolve_hostname.cache: dict[ str, str ] = { }

    cache: dict[ str, str ] = _resolve_hostname.cache

    if ip_address not in cache:
        try:
            hostname, _, _  = socket.gethostbyaddr( ip_address )
        except socket.herror:
            hostname        = ip_address
        cache[ ip_address ] = hostname

    return cache[ip_address]

def progress4(filename, size, sent, peername) -> None:
    """
    Extended progress callback including remote peer info.

    Args:
        filename: Name of the file being transferred.
        size: Total file size in bytes.
        sent: Bytes sent so far.
        peername: (host, port) tuple of the remote endpoint.

    Prints percentage completion with peer address to stdout.
    """
    hostname: str =  _resolve_hostname( peername[ 0 ] )
    sys.stdout.write("(%s:%s) %s progress: %.2f%%   \r" % ( hostname, peername[ 1 ], filename, float( sent )/float( size )*100 ) )

def _upload_tar_via_scp( file: IO[str], username: str, totp: str, password: str, saga_location: str ) -> None:
    """
    Upload a single local tar file to its remote path via an existing SCP session.

    Asserts that the remote target does not already exist, then performs a single
    SCP put operation. Does not perform verification by hashing the uploaded files.

    Returns None on success.

    Raises RuntimeError if remote file exists or if the files passed are not in absolute format
    """
 
     try:
        sftp_client: paramiko.SFTPClient = paramiko.SFTPClient.from_transport( demux.transport )
        try:
            sftp_client.stat( file_entry[ saga_location ] )
        except FileNotFoundError:
            pass
        else:
            message = f"RuntimeError: Remote file already exists: {demux.hostname}:{saga_location}"
            message += "Refusing to overwrite. Delete/move remote file first and then try to upload again."
            logger.critical( message )
            raise RuntimeError( message)
    finally:
        try:
            sftp_client.close( )
        except Exception:
            pass

    scp_client = SCPClient( demux.transport, progress4 = progress4 )

    try: 
        scp_client.put( file, os.path.join( saga_location, os.path.basename( file ) ) )  # file and saga_location must be in absolute format

    except scp.SCPException as error:
        raise
    finally:
        scp_client.close( )

    logger.info( f"Done: LOCAL:{tar_file:<{longest_local_path}} REMOTE:{demux.hostname}:{tar_file}" )



def _preflight_check(file: IO[str], username: str, totp: str, password: str, saga_location: str) -> None:
    """
    Validate input parameters before initiating an ATLAS file upload to SAGA.

    Performs defensive checks to ensure:
    - The provided file-like object is non-empty.
    - Required authentication fields (username and TOTP) are present.
    - A SAGA destination path is provided and is absolute.

    Logs a critical message and raises RuntimeError if any validation fails.

    Parameters:
        file:          Text-mode file-like object representing the ATLAS file to upload.
        username:      SAGA account username.
        totp:          Time-based one-time password for 2FA.
        password:      Account password (validated elsewhere if required).
        saga_location: Absolute destination path on SAGA.

    Raises:
        RuntimeError: If any required input is missing or invalid.
    """

    if len( file ) == 0:
        message = f"Length of ATLAS file to upload was zero while copying." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not username:
        message = f"username required while uploading to SAGA." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not topt:
        message = f"2FA is required to upload a file to SAGA." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not saga_location:
        message = f"SAGA upload location is required to upload ATLAS file." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not os.path.isabs( saga_location ):
        message = f"SAGA upload location must be supplied in absolute format." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )



def _upload_csv_to_saga( file: IO[str], username: str, totp: str, password: str, saga_location: str ) -> None:
    """
    Dispatch tar uploads to NIRD using the access mode defined on `demux`
    (SSH, SSH+2FA, or mounted sshfs) and execute transfers either serially
    or via a ThreadPoolExecutor.

    Serial mode executes uploads inline and fails immediately on error.
    Parallel mode submits one future per tar, blocks until ALL_COMPLETE,
    collects per-tar exceptions (including EOFError from transport drops),
    and raises a single RuntimeError after synchronization if any upload failed.

    """

    logger = logging.getLogger(__name__)
    logging.basicConfig( level=logging.INFO ) 

    _preflight_check( file: IO[str], username: str, totp: str, password: str, saga_location: str )

    #elif constants.NIRD_MODE_SSH_2FA == demux.nird_access_mode:
    _upload_tar_via_scp( file: IO[str], username: str, totp: str, password: str, saga_location: str )