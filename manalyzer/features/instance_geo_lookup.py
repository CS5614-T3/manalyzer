from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from manalyzer.features.common import PAGE_SIZE


GEOIP_API_URL = "http://ip-api.com/json/{ip}?fields=status,message,country,regionName,city,lat,lon,query,isp,org"
LOOKUP_INTERVAL_SECONDS = 5
TIMEOUT_SECONDS = 5
INSTANCE_TABLE = "instances_raw"
GEO_COLUMNS = ("server_lat", "server_lon", "server_loc_country", "server_loc_region", "server_loc_city")


@dataclass
class GeoLookupResult:
    name: str
    domain: str | None = None
    ip: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    provider: str | None = None
    error: str | None = None


def normalize_domain(name: str | None) -> str | None:
    if not name:
        return None

    value = name.strip()
    if not value:
        return None

    parsed = urlparse(value if "://" in value else f"//{value}")
    domain = parsed.hostname or value.split("/")[0]
    return domain.strip().lower().rstrip(".") or None


def resolve_ip(domain: str) -> str:
    addresses = socket.getaddrinfo(domain, None, proto=socket.IPPROTO_TCP)
    for address in addresses:
        ip = address[4][0]
        parsed_ip = ipaddress.ip_address(ip)
        if parsed_ip.version == 4:
            return ip
    if addresses:
        return addresses[0][4][0]
    raise socket.gaierror(f"No DNS result for {domain}")


def lookup_geoip(ip: str) -> dict:
    with urlopen(GEOIP_API_URL.format(ip=ip), timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def lookup_instance(name: str) -> GeoLookupResult:
    domain = normalize_domain(name)
    if not domain:
        return GeoLookupResult(name=name, error="empty domain")

    try:
        ip = resolve_ip(domain)
    except socket.gaierror as exc:
        return GeoLookupResult(name=name, domain=domain, error=f"DNS failed: {exc}")

    try:
        geo = lookup_geoip(ip)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return GeoLookupResult(name=name, domain=domain, ip=ip, error=f"GeoIP failed: {exc}")

    if geo.get("status") != "success":
        return GeoLookupResult(
            name=name,
            domain=domain,
            ip=ip,
            error=f"GeoIP failed: {geo.get('message') or 'unknown error'}",
        )

    return GeoLookupResult(
        name=name,
        domain=domain,
        ip=ip,
        country=geo.get("country"),
        region=geo.get("regionName"),
        city=geo.get("city"),
        lat=geo.get("lat"),
        lon=geo.get("lon"),
        provider=geo.get("org") or geo.get("isp"),
    )


def print_result(result: GeoLookupResult) -> None:
    location_parts = [part for part in (result.country, result.region, result.city) if part]
    location = " / ".join(location_parts) if location_parts else "-"
    coordinates = "-"
    if result.lat is not None and result.lon is not None:
        coordinates = f"{result.lat}, {result.lon}"

    print(f"name      : {result.name}")
    print(f"domain    : {result.domain or '-'}")
    print(f"ip        : {result.ip or '-'}")
    print(f"location  : {location}")
    print(f"lat/lon   : {coordinates}")
    print(f"provider  : {result.provider or '-'}")
    if result.error:
        print(f"error     : {result.error}")
    print("-" * 72)


def is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def has_missing_geo(row: dict) -> bool:
    return any(is_missing(row.get(column)) for column in GEO_COLUMNS)


def fetch_missing_geo_instances(supabase) -> list[dict]:
    rows = []
    start = 0
    select = "id,name,server_lat,server_lon,server_loc_country,server_loc_region,server_loc_city"
    missing_filter = (
        "server_lat.is.null,"
        "server_lon.is.null,"
        "server_loc_country.is.null,"
        "server_loc_region.is.null,"
        "server_loc_city.is.null,"
        "server_loc_country.eq.,"
        "server_loc_region.eq.,"
        "server_loc_city.eq."
    )

    while True:
        response = (
            supabase.table(INSTANCE_TABLE)
            .select(select)
            .or_(missing_filter)
            .order("name")
            .range(start, start + PAGE_SIZE - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(row for row in page if row.get("name") and has_missing_geo(row))
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def geo_update_payload(row: dict, result: GeoLookupResult) -> dict:
    values = {
        "server_lat": result.lat,
        "server_lon": result.lon,
        "server_loc_country": result.country,
        "server_loc_region": result.region,
        "server_loc_city": result.city,
    }
    return {
        column: value
        for column, value in values.items()
        if is_missing(row.get(column)) and value is not None and (not isinstance(value, str) or value.strip())
    }


def update_instance_geo(supabase, row: dict, payload: dict) -> None:
    supabase.table(INSTANCE_TABLE).update(payload).eq("name", row["name"]).execute()


def run(supabase):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    instances = fetch_missing_geo_instances(supabase)

    if not instances:
        print("instance_geo_lookup skipped: no instances_raw rows with missing location data")
        return

    print(f"instance_geo_lookup: filling missing location data for {len(instances)} instance(s)")
    print("note: location is based on DNS IP GeoIP, so CDN/proxy locations may be shown.")
    print("-" * 72)

    updated_count = 0
    skipped_count = 0
    for index, row in enumerate(instances, start=1):
        if index > 1:
            time.sleep(LOOKUP_INTERVAL_SECONDS)

        name = row["name"]
        result = lookup_instance(name)
        print_result(result)

        if result.error:
            skipped_count += 1
            continue

        payload = geo_update_payload(row, result)
        if not payload:
            skipped_count += 1
            continue

        update_instance_geo(supabase, row, payload)
        updated_count += 1
        print(f"updated   : {', '.join(sorted(payload))}")
        print("-" * 72)

    print(f"instance_geo_lookup done: updated {updated_count}, skipped {skipped_count}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Look up approximate server locations for Mastodon instances.")
    parser.add_argument(
        "names",
        nargs="*",
        help="Instance domains to look up. If omitted, names are loaded from instances_raw.",
    )
    return parser


def main():
    from manalyzer.db_client import get_db_client

    args = build_parser().parse_args()
    if args.names:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")
        print(f"instance_geo_lookup: showing {len(args.names)} provided instance(s)")
        print("note: location is based on DNS IP GeoIP, so CDN/proxy locations may be shown.")
        print("-" * 72)
        for name in args.names:
            print_result(lookup_instance(name))
        return

    run(get_db_client())


if __name__ == "__main__":
    main()
