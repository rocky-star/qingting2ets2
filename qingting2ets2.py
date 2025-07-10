#!/usr/bin/env python3

import sys
import itertools
from collections.abc import Sequence
import json
from typing import TypedDict, NotRequired
import logging
import argparse
import locale
import urllib.request

ENDPOINT_URL = 'https://webbff.qtfm.cn/www'
SII_HEADER = """\
SiiNunit
{
#
# Stream data format: "URL of the live stream | Name for the radio as listed in Radio screen | Genre | Language | Bitrate"
#
# !!! WARNING !!!  mms streams are not supported!
#
# remove the leading '#' character on the "stream_data[]" line below and enter
# a correct URL of the stream to have the Internet radio offered in the Radio screen
# you can enter multiple lines in the same format, each defining additional radios
#

live_stream_def : .live_streams {
# stream_data[]: "URL of mp3 live stream|Radio name|Genre|Language|Bitrate"
"""
SII_FOOTER = """\
}
}
"""


class QuerySpec(TypedDict):
    name: str
    alias: NotRequired[str]
    params: NotRequired[dict[str, object]]
    fields: set[str]


class QueryBody(TypedDict):
    query: str


class RadioStation(TypedDict):
    id: int
    name: str
    categories: list[str]


def dump_query_sepc(spec: QuerySpec) -> str:
    result = spec['name']
    if 'alias' in spec:
        result = spec['alias'] + ': ' + result
    if 'params' in spec:
        result += '('
        result += ', '.join(f'{k}: {json.dumps(v)}'
                            for k, v in spec['params'].items())
        result += ')'
    result += ' {' + ', '.join(spec['fields']) + '}'

    return result


def make_query(*specs: QuerySpec) -> QueryBody:
    return {'query': '{' + ' '.join(dump_query_sepc(s) for s in specs) + '}'}


def make_request(query_body: QueryBody) -> urllib.request.Request:
    return urllib.request.Request(
        ENDPOINT_URL,
        json.dumps(query_body).encode(),
        {'Content-Type': 'application/json'}
    )


def escape_unicode(s: str) -> str:
    return ''.join(chr(c) if c < 0x7F else ('\\x' + hex(c)[2:].rjust(2, '0'))
                   for c in s.encode('utf_8'))


def main(argv: Sequence[str]) -> None:
    locale.setlocale(locale.LC_ALL, '')

    parser = argparse.ArgumentParser(
        prog=argv[0],
        description=(
            'Retrieve radio stations on Qingting FM and '
            'convert them into ETS2/ATS-compatible format.'
        ),
    )
    parser.add_argument(
        '--output', '-o',
        default='live_streams.sii',
        help='the name of the output .sii file',
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='increase the log level',
    )
    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        level=(logging.DEBUG if args.verbose else logging.INFO),
    )

    logging.debug('Getting available regions and classes')
    regions: dict[str, int] = {}
    classes: dict[str, int] = {}
    req = make_request(
        make_query({'name': 'radioPage', 'fields': {'regions', 'classes'}})
    )
    with urllib.request.urlopen(req) as resp:
        json_body = json.load(resp)
        regions.update((obj['title'], obj['id'])
                       for obj in json_body['data']['radioPage']['regions'])
        classes.update((obj['title'], obj['id'])
                       for obj in json_body['data']['radioPage']['classes'])
    logging.info('Retrieved %d regions and %d classes',
                 len(regions), len(classes))

    radio_stations: dict[str, RadioStation] = {}
    for cname, cid in itertools.chain(regions.items(), classes.items()):
        logging.info('Getting radio stations of %s (#%d)', cname, cid)

        n_added = n_updated = 0
        page_no = 1
        while True:
            spec: QuerySpec = {'name': 'radioPage',
                    'params': {'cid': cid, 'page': page_no},
                    'fields': {'contents'}}
            req = make_request(make_query(spec))
            with urllib.request.urlopen(req) as resp:
                json_body = json.load(resp)
                for station_obj in json_body['data']['radioPage']['contents']['items']:
                    try:
                        radio_stations[station_obj['title']]['categories'].append(cname)
                        n_updated += 1
                    except KeyError:
                        radio_stations[station_obj['title']] = {
                            'id': station_obj['id'],
                            'name': station_obj['title'],
                            'categories': [cname],
                        }
                        n_added += 1

                if n_added + n_updated < json_body['data']['radioPage']['contents']['count']:
                    page_no += 1
                else:
                    break

        logging.info('Added %d radio station(s), updated %d radio station(s)',
                     n_added, n_updated)

    logging.info('Writing the output file')
    with open(args.output, 'w', encoding='ascii') as f:
        f.write(SII_HEADER)
        for station in radio_stations.values():
            line = 'stream_data[]: '
            line += f"\"https://lhttp-hw.qtfm.cn/live/{station['id']}/64k.mp3"
            line += f"|{station['name'].replace('"', '\\"')}"
            line += f"|{' '.join(station['categories'])}"
            line += '|ZH|64|0"\n'
            f.write(escape_unicode(line))
        f.write(SII_FOOTER)


if __name__ == '__main__':
    main(sys.argv)
