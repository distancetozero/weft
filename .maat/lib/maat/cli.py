"""Shared argument handling for the casebook executables."""
from __future__ import annotations

import argparse
import datetime

from . import cases


def date_arg(value: str) -> str:
    if not cases.valid_date(value):
        raise argparse.ArgumentTypeError("`%s` is not a date as YYYY-MM-DD" % value)
    return value


def add_dates(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--model-since", metavar="YYYY-MM-DD", type=date_arg,
                    help="default: the model date in the maat-lessons skill")
    ap.add_argument("--today", metavar="YYYY-MM-DD", type=date_arg,
                    default=datetime.date.today().isoformat())


def model_since(args: argparse.Namespace, plugin_root) -> "str | None":
    return args.model_since or cases.current_model_date(str(plugin_root))
