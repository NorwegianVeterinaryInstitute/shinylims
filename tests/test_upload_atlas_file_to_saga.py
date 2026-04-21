from __future__ import annotations

import io

import pytest

from shinylims.integrations.upload_atlas_file_to_saga import (
    _preflight_check,
    _validate_atlas_csv,
)

VALID_CSV = "Sample Name,NIRD Filename\nSample1,file1.fastq\nSample2,file2.fastq\n"


def make_buffer(content: str = VALID_CSV) -> io.StringIO:
    return io.StringIO(content)


# ── _validate_atlas_csv ──────────────────────────────────────────────────────

def test_validate_atlas_csv_valid_passes():
    _validate_atlas_csv(make_buffer())  # must not raise


def test_validate_atlas_csv_empty_file_raises():
    with pytest.raises(RuntimeError, match="empty or missing"):
        _validate_atlas_csv(io.StringIO(""))


def test_validate_atlas_csv_header_only_no_rows_passes():
    _validate_atlas_csv(make_buffer("Sample Name,NIRD Filename\n"))


def test_validate_atlas_csv_missing_nird_filename_column_raises():
    buf = make_buffer("Sample Name,Other Column\nS1,x\n")
    with pytest.raises(RuntimeError, match="missing required column"):
        _validate_atlas_csv(buf)


def test_validate_atlas_csv_missing_sample_name_column_raises():
    buf = make_buffer("NIRD Filename,Other\nfile1.fastq,x\n")
    with pytest.raises(RuntimeError, match="missing required column"):
        _validate_atlas_csv(buf)


def test_validate_atlas_csv_empty_sample_name_raises():
    buf = make_buffer("Sample Name,NIRD Filename\n,file1.fastq\n")
    with pytest.raises(RuntimeError, match="empty"):
        _validate_atlas_csv(buf)


def test_validate_atlas_csv_empty_nird_filename_raises():
    buf = make_buffer("Sample Name,NIRD Filename\nSample1,\n")
    with pytest.raises(RuntimeError, match="empty"):
        _validate_atlas_csv(buf)


def test_validate_atlas_csv_whitespace_only_values_count_as_empty():
    buf = make_buffer("Sample Name,NIRD Filename\n   ,file1.fastq\n")
    with pytest.raises(RuntimeError, match="empty"):
        _validate_atlas_csv(buf)


def test_validate_atlas_csv_resets_seek_position_after_validation():
    buf = make_buffer()
    _validate_atlas_csv(buf)
    assert buf.tell() == 0


def test_validate_atlas_csv_reports_bad_row_numbers():
    buf = make_buffer("Sample Name,NIRD Filename\nGood,file.fastq\n,missing_sample\n")
    with pytest.raises(RuntimeError, match="row"):
        _validate_atlas_csv(buf)


# ── _preflight_check ─────────────────────────────────────────────────────────

def test_preflight_valid_inputs_pass():
    _preflight_check(
        make_buffer(), "validuser", "123456", "secret", "/cluster/shared/out.csv"
    )


def test_preflight_empty_username_raises():
    with pytest.raises(RuntimeError, match="[Uu]sername"):
        _preflight_check(make_buffer(), "", "123456", "secret", "/cluster/shared/out.csv")


def test_preflight_username_with_asterisk_raises():
    with pytest.raises(RuntimeError, match=r"\*"):
        _preflight_check(
            make_buffer(), "user*name", "123456", "secret", "/cluster/shared/out.csv"
        )


def test_preflight_username_with_uppercase_raises():
    with pytest.raises(RuntimeError, match="Invalid username"):
        _preflight_check(
            make_buffer(), "UserName", "123456", "secret", "/cluster/shared/out.csv"
        )


def test_preflight_username_with_space_raises():
    with pytest.raises(RuntimeError, match="Invalid username"):
        _preflight_check(
            make_buffer(), "user name", "123456", "secret", "/cluster/shared/out.csv"
        )


def test_preflight_username_starting_with_digit_raises():
    with pytest.raises(RuntimeError, match="Invalid username"):
        _preflight_check(
            make_buffer(), "1user", "123456", "secret", "/cluster/shared/out.csv"
        )


def test_preflight_empty_totp_raises():
    with pytest.raises(RuntimeError, match="2FA"):
        _preflight_check(make_buffer(), "validuser", "", "secret", "/cluster/shared/out.csv")


def test_preflight_non_digit_totp_raises():
    with pytest.raises(RuntimeError, match="digit"):
        _preflight_check(
            make_buffer(), "validuser", "abc123", "secret", "/cluster/shared/out.csv"
        )


def test_preflight_totp_too_short_raises():
    with pytest.raises(RuntimeError, match="six digits"):
        _preflight_check(
            make_buffer(), "validuser", "12345", "secret", "/cluster/shared/out.csv"
        )


def test_preflight_totp_too_long_raises():
    with pytest.raises(RuntimeError, match="six digits"):
        _preflight_check(
            make_buffer(), "validuser", "1234567", "secret", "/cluster/shared/out.csv"
        )


def test_preflight_empty_password_raises():
    with pytest.raises(RuntimeError, match="[Pp]assword"):
        _preflight_check(make_buffer(), "validuser", "123456", "", "/cluster/shared/out.csv")


def test_preflight_empty_saga_location_raises():
    with pytest.raises(RuntimeError, match="[Ll]ocation"):
        _preflight_check(make_buffer(), "validuser", "123456", "secret", "")


def test_preflight_relative_saga_location_raises():
    with pytest.raises(RuntimeError, match="absolute"):
        _preflight_check(
            make_buffer(), "validuser", "123456", "secret", "relative/path/out.csv"
        )


def test_preflight_saga_location_without_csv_extension_raises():
    with pytest.raises(RuntimeError, match=r"\.csv"):
        _preflight_check(
            make_buffer(), "validuser", "123456", "secret", "/cluster/shared/out.txt"
        )


def test_preflight_saga_location_directory_only_raises():
    with pytest.raises(RuntimeError, match=r"\.csv"):
        _preflight_check(
            make_buffer(), "validuser", "123456", "secret", "/cluster/shared/"
        )


def test_preflight_underscore_in_username_is_valid():
    _preflight_check(
        make_buffer(), "valid_user", "123456", "secret", "/cluster/shared/out.csv"
    )


def test_preflight_hyphen_in_username_is_valid():
    _preflight_check(
        make_buffer(), "valid-user", "123456", "secret", "/cluster/shared/out.csv"
    )
