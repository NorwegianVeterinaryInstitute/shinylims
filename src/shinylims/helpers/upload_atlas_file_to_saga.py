import logging
import os
import io
import pathlib
import paramiko
import paramiko.sftp
import scp
import stat
from src.shinylims.helpers.ssh_transport import _ensure_remote_present_file_via_sftp
from src.shinylims.helpers.ssh_transport import _connect
from src.shinylims.helpers.ssh_transport import _validate_hostkey
from src.shinylims.helpers.ssh_transport import _authenticate_transport

from typing import Union, IO # generic file-like object


def _upload_tar_via_scp( buffer: IO[str], transport: paramiko.Transport, username: str, totp: str, password: str, saga_location: str ) -> None:
    """
    Upload a single local file to its remote path via an sftp session.

    Asserts that the remote target does not already exist, then performs a single
    sftp put operation.

    Returns None on success.

    Raises
        RuntimeError if remote file exists or if the files passed are not in absolute format
    """

    logger                                          = logging.getLogger(__name__)
    ip, port                                        = transport.getpeername( )
    basedir:str                                     = str( pathlib.Path( saga_location ).parent ) # e.x. /cluster/shared/vetinst/users/georgmar/atlas_export_20260227_122753.csv -> /cluster/shared/vetinst/users/georgmar
    attributes: paramiko.sftp_attr.SFTPAttributes   = None
    dir_exists: bool                                = False
    val:int                                         = 0
    sftp_client: paramiko.SFTPClient                = None


    if transport is None:
        message = "Transport for file is not set, aborting"
        logger.critical( message )
        raise RuntimeError( message)

    if not transport.is_active( ):
        raise OSError( 9, "Peer closed the connection" )

    try:
        sftp_client = paramiko.SFTPClient.from_transport( transport )
    except:
        message = f"SFTPError: failed to create SFTP session at hop {ip}:{port}"
        logger.critical( message )
        raise paramiko.SSHException( message ) from error
    try:
        buf = io.BytesIO( buffer.getvalue( ) )  # str -> bytes
        attributes = sftp_client.putfo( fl = buf, remotepath = saga_location, confirm = True )  # file and saga_location must be in absolute format
        isinstance( attributes, paramiko.SFTPAttributes ) # success is defined by "no exception raised".
    except:
        message = f"SFTPError: failed to upload file during SFTP session at hop {ip}:{port}"
        logger.critical( message )
        raise paramiko.SSHException( message ) from error
    finally:
        sftp_client.close( )

    logger.info( f"Done uploading {saga_location}!" )



def _preflight_check( local_file: IO[str], username: str, totp: str, password: str, saga_location: str) -> None:
    """
    Validate input parameters before initiating an ATLAS file upload to SAGA.

    Performs defensive checks to ensure:
    - The provided file-like object is non-empty.
    - Required authentication fields (username, TOTP and password) are present.
    - A SAGA destination path is provided and is absolute.
    - local_file path, if provided, is absolute, or an IO stream

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

    logger = logging.getLogger(__name__)

    if len( local_file.getvalue() ) == 0:
        message = f"Length of ATLAS file to upload was zero while copying." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not username:
        message = f"Username required while uploading to SAGA." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if '*' in username:
        message= "'*' cannot be part of a username. Aborting." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not username.isalnum( ):
        message = f"Username must be alphanumeric with no spaces." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not totp:
        message = f"2FA token is required to upload a file to SAGA." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not totp.isdigit( ) or len( totp ) != 6:
        message = f"2FA token must be all digits and six digits long"
        logger.critical( message )
        raise RuntimeError( message )

    if '*' in totp:
        message = "'*' cannot be part of a totp. Aborting." # check if we got passed garbage
        logger.critical( message )
        raise RuntimeError( message )

    if not password:
        message = "Empty password for uploading ATLAS csv file to SAGA. Aborting."
        logger.critical( message )
        raise RuntimeError( message )

    if '*' in password:
        message = "Password for uploading ATLAS csv file to SAGA cannot contain '*'. Aborting."
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

    base = os.path.basename( saga_location )
    if not base or not base != os.sep and os.path.splitext( base )[ 1 ].lower( ) == ".csv": # make sure we got a filename and that it ends in .csv
        message = f"SAGA remote location does not contain a filename at the end of path or filename does not end in '.csv'"
        logger.critical( message )
        raise RuntimeError( message )



def _upload_csv_to_saga( file: Union[ str, os.PathLike, IO[ str ] ], username: str, totp: str, password: str, saga_location: str ) -> None:
    """
    Upload the ATLAS scv file to SAGA
    """

    logger = logging.getLogger(__name__)
    logging.basicConfig( level = logging.DEBUG )
    hop:str = "login.saga.sigma2.no"              # we can nail this here. this DNS entry in Round-Robin format and there are 5 login nodes
                                                  # the only real concern is to add the ssh host key for all five nodes


    transport: paramiko.Transport = None

    data = open( os.fspath( file ) ).read( ) if isinstance( file, ( str, os.PathLike ) ) else file.read( )
    buffer = io.StringIO( data )

    logger.debug( f"file input is: {file}" )
    logger.debug( f"buffer is: {buffer.getvalue( )}" )
    logger.debug( f"saga_location is: {saga_location}" )

    _preflight_check( buffer, username, totp, password, saga_location )

    transport = _connect( hop )
    _validate_hostkey( hop, transport )
    _authenticate_transport( hop = hop, transport = transport, username = username, password = password, totp = totp  ) # auth only by 2FA
    _ensure_remote_present_file_via_sftp( transport, saga_location )
    _upload_tar_via_scp( buffer, transport, username, totp, password, saga_location ) # FIX THIS TO INCLUDE REMOTE FILE CHECKING?
