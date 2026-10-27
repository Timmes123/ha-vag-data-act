#!/usr/bin/env python3
"""Trace the portal login + dataset listing from the command line.

Credentials are read from the environment (``VAG_EMAIL``, ``VAG_PASSWORD``) or asked
interactively; they are never written to disk. Every redirect hop is printed with
code/state values redacted.

    VAG_EMAIL=me@example.com python tools/login_trace.py [--brand CUPRA] [--country de]
        [--language de] [--vin VSSZZZ…] [--download out.zip]
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from custom_components.vag_data_act import api
from custom_components.vag_data_act.parser import parse_dataset


async def main(args: argparse.Namespace) -> int:
    email = os.environ.get("VAG_EMAIL") or input("Portal e-mail: ")
    password = os.environ.get("VAG_PASSWORD") or getpass.getpass("Portal password: ")
    jar = aiohttp.CookieJar()
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        client = api.PortalClient(
            session, email, password, brand=args.brand, country=args.country, language=args.language
        )
        try:
            await client.async_login()
        except api.PortalError as err:
            print(f"LOGIN FAILED: {type(err).__name__}: {err}")
            for hop in client.last_login_hops:
                print(f"  {hop.method} {api.redact_url(hop.url)} -> {hop.status}")
            return 1
        print("LOGIN OK; redirect chain:")
        for hop in client.last_login_hops:
            print(f"  {hop.method} {api.redact_url(hop.url)} -> {hop.status}")
        print(f"cookies: {[c.key for c in jar]}")
        vehicles = await client.async_list_vehicles()
        for v in vehicles:
            print(f"vehicle: …{v.vin[-4:]} nickname={v.nickname!r} model={v.model!r}")
        vin = args.vin or (vehicles[0].vin if vehicles else None)
        if not vin:
            print("no vehicle")
            return 1
        identifier = await client.async_get_identifier(vin)
        print(f"identifier: {identifier}")
        datasets = await client.async_list_datasets(vin, identifier)
        print(f"{len(datasets)} datasets listed")
        for d in sorted(datasets, key=lambda d: d.created_on or 0)[-5:]:
            print(f"  {d.name} created={d.created_on} size={d.size}")
        newest = api.newest_dataset(datasets)
        if newest is None:
            print("no content dataset")
            return 0
        ds = await client.async_download_dataset(vin, identifier, newest.name)
        print(
            f"downloaded {ds.zip_name}: inner={ds.inner_name} sha256={ds.sha256[:16]} bytes={len(ds.content)}"
        )
        parsed = parse_dataset(ds.content)
        print(f"points={parsed.point_count} last_vehicle_report={parsed.last_vehicle_report}")
        for name in ("soc", "odometer", "range", "charging_state", "target_soc_effective"):
            print(f"  {name} = {parsed.get(name)!r}")
        print(f"ambiguities: {[a.name for a in parsed.ambiguities]}")
        print(f"unmapped: {len(parsed.unmapped)}")
        if args.download:
            Path(args.download).write_bytes(ds.content)
            print(f"inner JSON written to {args.download}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--brand", default="CUPRA")
    p.add_argument("--country", default="de")
    p.add_argument("--language", default="de")
    p.add_argument("--vin")
    p.add_argument("--download", help="write the inner JSON to this file")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG log (full hop log)")
    ns = p.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if ns.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    sys.exit(asyncio.run(main(ns)))
