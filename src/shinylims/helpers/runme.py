#!/usr/bin/python3.11

import json
import logging
import io
import sys
import urllib.request

from upload_atlas_file_to_saga import _upload_csv_to_saga
# import ssh_transport


import json, urllib.request

def _bw_item( item_id: str ) -> dict:
    with urllib.request.urlopen( f"http://127.0.0.1:8087/object/{item_id}/login.saga.sigma2.no" ) as r:
        return json.load( r )[ "data" ][ "data" ]

def _get_username( ) -> str:
    return _bw_item( "username" )
def _get_password( ) -> str:
    return _bw_item( "password" )
def _get_totp( ) -> str:
    return _bw_item( "totp" )


def main( ) -> None:

    username:str = _get_username( )
    password:str = _get_password( )
    totp:str     = _get_totp( )

    logger = logging.getLogger( __name__ )
    logging.basicConfig( level = logging.DEBUG )


    logger.debug( f"username: {username}" )
    logger.debug( f"password: {password }" )
    logger.debug( f"totp:     {totp}" )

    mock_file: io.StringIO = io.StringIO("col1,col2\n1,2\n")
    mock_file.seek(0)  # ensure pointer at start

    # _upload_csv_to_saga( file: Union[ str, os.PathLike, IO[ str ] ], username = username, password = password, totp = totp, saga_location = "/cluster/shared/vetinst/users/georgmar/atlas_export_2026-02-27T15:05:03.csv" )
    _upload_csv_to_saga( file = mock_file, username = username, password = password, totp = totp, saga_location = "/cluster/shared/vetinst/users/georgmar/atlas_export_2026-02-27T15:05:03.csv" )


main( )