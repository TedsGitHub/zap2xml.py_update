#! /usr/bin/python

import getopt
import sys
import os
import time
import urllib.parse
import zlib
import json
import requests
from fake_useragent import UserAgent
from PIL import Image
import re


def HELP_MESSAGE():
    print("""zap2xml <zap2xml@gmail.com> (version)
  -u <username>
  -p <password>
  -d <# of days> (default = days)
  -n <# of no-cache days> (from end)   (default = ncdays)
  -N <# of no-cache days> (from start) (default = ncsdays)
  -B <no-cache day>
  -s <start day offset> (default = start)
  -o <output xml filename> (default = "outFile")
  -c <cacheDirectory> (default = "cacheDir")
  -l <lang> (default = "lang")
  -i <iconDirectory> (default = don't download channel icons)
  -m <#> = offset program times by # minutes (better to use TZ env var)
  -b = retain website channel order
  -x = output XTVD xml file format (default = XMLTV)
  -w = wait on exit (require keypress before exiting)
  -q = quiet (no status output)
  -r <# of connection retries before failure> (default = retries, max 20)
  -e = hex encode entities (html special characters like accents)
  -E "amp apos quot lt gt" = selectively encode standard XML entities
  -F = output channel names first (rather than "number name")
  -O = use old tv_grab_na style channel ids (C###nnnn.gracenote.com)
  -A "new live" = append " *" to program titles that are "new" and/or "live"
  -M = copy movie_year to empty movie sub-title tags
  -U = UTF-8 encoding (default = "ISO-8859-1")
  -L = output "<live />" tag (not part of xmltv.dtd)
  -T = don't cache files containing programs with "sTBA" titles
  -P <http://proxyhost:port> = to use an http proxy
  -C <configuration file> (default = "confFile")
  -S <#seconds> = sleep between requests to prevent flooding of server
  -D = include details = 1 extra http request per program!
  -I = include icons (image URLs) - 1 extra http request per program!
  -J <xmltv> = include xmltv file in output
  -Y <lineupId> (if not using username/password)
  -Z <zipcode> (if not using username/password)
  -z = use tvguide.com instead of gracenote.com
  -a = output all channels (not just favorites)
  -j = add "series" category to all non-movie programs""")
    time.sleep(5) if os.name == 'nt' else None
    exit(0)

options = {}
opts, args = getopt.getopt(sys.argv[1:], "?aA:bB:c:C:d:DeE:Fgi:IjJ:l:Lm:Mn:N:o:Op:P:qRr:s:S:t:Tu:UwWxY:zZ:89")
for opt, arg in opts:
    options[opt.lstrip('-')] = arg

# Defaults
requests_session = requests.Session()
requests_sessionheaders = {
    'User-Agent': 'Mozilla/5.0 (X11; U; Linux i686) Gecko/20071127 Firefox/2.0.0.11',
    'Accept-Encoding': 'gzip, deflate'
}

logged_in = False

start = int(0)
days = int(7)
ncdays = int(0)
ncsdays = int(0)
ncmday = int(-1)
retries = int(3)
outFile = 'xmltv.xml'
if 'x' in options:
    outFile = 'xtvd.xml'
cacheDir = 'cache'
lang = 'en'
userEmail = ''
password = ''
proxy = None
postalcode = None
country = None
lineupId = None
device = None
sleeptime = 0
allChan = 0
shiftMinutes = 0

outputXTVD = 0
lineuptype = None
lineupname = None
lineuplocation = None

zapToken = None
zapPref = '-'
zapFavorites = {}
sidCache = {}

sTBA = r"\bTBA\b|To Be Announced"

tvgfavs = {}

if 'h' in options:
    HELP_MESSAGE()

if 'C' in options:
    confFile = options['C']

    # read config file
    if os.path.exists(confFile):
        print(f"Reading config file: {confFile}")
        with open(confFile, 'r') as conf:
            for line in conf:
                if line.strip().lower().startswith("lineupname="):
                    lineupname = line.strip().split("=")[1].strip()
                elif line.strip().lower().startswith("lineuptype="):
                    lineuptype = line.strip().split("=")[1].strip()
                elif line.strip().lower().startswith("lineuplocation="):
                    lineuplocation = line.strip().split("=")[1].strip()
                elif line.strip().lower().startswith("postalcode="):
                    postalcode = line.strip().split("=")[1].strip()
                else:
                    raise ValueError(f"Oddline in config file \"{confFile}\".\n\t{line.strip()}")

if not options and userEmail == '':
    HELP_MESSAGE()

cacheDir = options.get('c', None)
days = options.get('d', None)
#ncdays = options.get('n', None)
#ncsdays = options.get('N', None)
#ncmday = options.get('B', None)
start = options.get('s', None)
retries = options.get('r', None)
iconDir = options.get('i', None)
trailerDir = options.get('t', None)
lang = options.get('l', None)
# outFile = options.get('o', None)
password = options.get('p', None)
userEmail = options.get('u', None)
proxy = options.get('P', None)
zlineupId = options.get('Y', None)
zipcode = options.get('Z', None)
includeXMLTV = options.get('J', None) if os.path.exists(options.get('J', '')) else None
outputXTVD = 1 if 'x' in options else 0
allChan = 1 if 'a' in options or (zipcode and zlineupId) else 0
sleeptime = options.get('S', None)
#shiftMinutes = options.get('m', None)

days = int(days)

if start is None:
    start = int(0)

if retries is None:
    retries = int(3)

if sleeptime is None:
    sleeptime = int(0)


if ncdays is not None:
    ncdays = days - ncdays

if ncdays is None:
    ncdays = int(0)

if cacheDir is None:
    cacheDir = "cache"

if lang is None:
    lang = 'en'

urlRoot = 'https://tvlistings.gracenote.com/'
urlAssets = 'https://zap2it.tmsimg.com/assets/'
tvgurlRoot = 'http://mobilelistings.tvguide.com/'
tvgMapiRoot = 'http://mapi.tvguide.com/'
tvgurl = 'https://www.tvguide.com/'
tvgspritesurl = 'http://static.tvgcdn.net/sprites/'

if retries is not None and retries > 20:
    retries = 20

programs = {}
cp = None
stations = {}
cs = None
rcs = None
schedule = {}
sch = None
logos = {}

coNum = 0
total_bytes = 0
total_requests = 0
tsocks = ()
expired = 0
tba = 0
exp = 0
fh = []

XTVD_startTime = None
XTVD_endTime = None

def log_warning(*args):
    print("Warning:", *args)

def pout(*args):
    if 'q' not in options:
        print(*args)

def incXML(st, en, FH):
    with open(includeXMLTV, 'r') as XF:
        for line in XF:
            if st in line or en in line:
                if en not in line:
                    FH.write(line)

def pl(i, s):
    r = f"{i} {s}"
    return r if i == 1 else r + "s"

def print_if_not_quiet(*args):
    if 'q' not in options:
        print(*args)

def warn(*args):
    print("Warning:", *args)

def right_trim(string):
    return string.rstrip()

def trim(string):
    return string.strip()

def trim_and_clean(string):
    trimmed_string = trim(string)
    return ''.join(char for char in trimmed_string if char.isalnum() or char in [' ', '(', ')', ',']).replace('  ', ' ')

def right_trim_last_three(string):
    return string[:-3]

def convert_time(timestamp):
    import time
    timestamp += shiftMinutes * 60 * 1000
    timestamp_secs = int(timestamp/1000)
    # print(f'timestamp is {timestamp_secs}')
    localtime = time.localtime(timestamp_secs)
    # print(f'localtime is {localtime}')
    return time.strftime("%Y%m%d%H%M%S", localtime)

def convert_time_xtvd(timestamp):
    timestamp += shiftMinutes * 60 * 1000
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(right_trim_last_three(timestamp)))

def convert_oad(timestamp):
    import time
    timestamp_secs = int(timestamp/1000)
    # print (f'timestamp is {timestamp_secs}')
    return time.strftime("%Y%m%d", time.gmtime(timestamp_secs))

def convert_oad_xtvd():
    return time.strftime("%Y-%m-%d", time.gmtime(right_trim_last_three(shift())))

def convert_duration_xtvd(duration):
    hour = int(duration / 3600000)
    minutes = int((duration - (hour * 3600000)) / 60000)
    return f"PT{hour:02d}H{minutes:02d}M"

def append_asterisk(title, schedule_key):
    if 'A' in options:
        if ('new' in options['A'] and 'new' in schedule_key) or \
           ('live' in options['A'] and 'live' in schedule_key):
            # print(f'append_asterisk')        
            title += " *"
    return title

def station_to_channel(station_key):
    if 'z' in options:
        return f"I{stations[station_key]['number']}.{stations[station_key]['stnNum']}.tvguide.com"
    elif 'O' in options:
        return f"C{stations[station_key]['number']}{stations[station_key]['name'].lower()}.gracenote.com"
    elif '9' in options:
        return f"I{stations[station_key]['stnNum']}.labs.gracenote.com"
    return f"I{stations[station_key]['number']}.{stations[station_key]['stnNum']}.gracenote.com"

def encode_lcl(text):
    if text is None:
        return text

    text = text.replace('…', '-')
    text = text.replace('\u0101', 'a')
    text = text.replace('\u0161', 'š')
    
    text = text.replace('Ã³', 'ó')
    text = text.replace('Ãº', 'ú')
    text = text.replace('Ã©', 'é')
    text = text.replace('Ã±', 'ñ')
    text = text.replace('Ã­ ­', 'í')
    text = text.replace('Ã¡', 'á')
    text = text.replace("Ã«", "ë")
    text = text.replace("Ã", "à")
    text = text.replace("Ã", "à")
    
    if 'U' not in options:
        text = text.encode('utf-8').decode('utf-8')
    if 'E' not in options or 'amp' in options['E']:
        text = text.replace('&', '&amp;')
    if 'E' not in options or 'quot' in options['E']:
        text = text.replace('"', '&quot;')
    if 'E' not in options or 'apos' in options['E']:
        text = text.replace("'", '&apos;')
    if 'E' not in options or 'lt' in options['E']:
        text = text.replace('<', '&lt;')
    if 'E' not in options or 'gt' in options['E']:
        text = text.replace('>', '&gt;')
    if 'e' in options:
        text = ''.join([f'&#{ord(char)};' if not (32 <= ord(char) <= 126) else char for char in text])
    return text

def print_header(file_handle, encoding):
    file_handle.write('<?xml version="1.0" encoding="{}"?>\n'.format(encoding))
    file_handle.write('<!DOCTYPE tv SYSTEM "xmltv.dtd">\n\n')
    if 'z' in options:
        file_handle.write('<tv source-info-url="http://tvguide.com/" source-info-name="tvguide.com"')
    else:
        file_handle.write('<tv source-info-url="http://tvlistings.gracenote.com/" source-info-name="gracenote.com"')
    file_handle.write(' generator-info-name="zap2xml" generator-info-url="zap2xml@gmail.com">\n')

def print_footer(file_handle):
    file_handle.write('</tv>\n')

def sort_chan(a, b):
    global stations
    # print(f'stations[a] {stations[a]}')
    # print(f'stations[b] {stations[b]}')
    if 'order' in stations[a] and 'order' in stations[b]:
        numa = float(stations[a]['order'])
        numb = float(stations[b]['order'])
        c = (numa > numb) - (numa < numb)
        if c == 0:
            return (stations[a]['stnNum'] > stations[b]['stnNum']) - (stations[a]['stnNum'] < stations[b]['stnNum'])
        else:
            return c
    else:
        print(f'order not found in station')
        return (stations[a]['name'] > stations[b]['name']) - (stations[a]['name'] < stations[b]['name'])


def print_channels(file_handle):

    from functools import cmp_to_key
    global options
    global stations

    sorted_stations = sorted(stations.keys(), key=cmp_to_key(sort_chan))

    for key in sorted_stations:
        # print(f'key {key}')

        station_name = encode_lcl(stations[key]['name'])
        #full_name = encode(stations[key]['fullname'])
        full_name = None
        station_number = stations[key]['number']
        file_handle.write(f'\t<channel id="{station_to_channel(key)}">\n')
        
        if 'F' in options and station_name:
            file_handle.write(f'\t\t<display-name>{station_name}</display-name>\n')
        
        if station_number is not None:
            copy_logo(key)
            if station_number != '':
                file_handle.write(f'\t\t<display-name>{station_number} {station_name}</display-name>\n')
                file_handle.write(f'\t\t<display-name>{station_number}</display-name>\n')

        if 'F' not in options and station_name:
            file_handle.write(f'\t\t<display-name>{station_name}</display-name>\n')
        
        if full_name:
            file_handle.write(f'\t\t<display-name>{full_name}</display-name>\n')
        
        if 'logoURL' in stations[key]:
            file_handle.write(f'\t\t<icon src="{stations[key]["logoURL"]}" />\n')
        
        file_handle.write('\t</channel>\n')

def print_programmes(file_handle):
    from functools import cmp_to_key
    sorted_station_keys = sorted(stations.keys(), key=cmp_to_key(sort_chan))
    
    for station in sorted_station_keys:
        index = 0
        key_array = sorted(schedule[station].keys(), key=lambda s: schedule[station][s]['time'])
        for s in key_array:
            if len(key_array) <= index and 'endtime' not in schedule[station][s]:
                del schedule[station][s]
                continue
            
            program = schedule[station][s]['program']
            start_time = convert_time(schedule[station][s]['time'])
            # print(f'start_time is {start_time}')
            start_timezone = timezone(schedule[station][s]['time'])
            # print(f'key_arry[index] is {key_array[index+1]}')
            # print(f'len(key_array) = {len(key_array)}')
            # print(f'index is {index}')
            if len(key_array) > index+1:
                end_time = schedule[station][s].get('endtime', schedule[station][key_array[index + 1]]['time'])
            else:
                del schedule[station][s]
                continue
            
            stop_time = convert_time(end_time)
            stop_timezone = timezone(end_time)

            file_handle.write(f'\t<programme start="{start_time} {start_timezone}" stop="{stop_time} {stop_timezone}" channel="{station_to_channel(schedule[station][s]["station"])}">\n')
            if 'title' in programs[program]:
                title = encode_lcl(programs[program]['title'])
                # print(f'program is {title}')
                schedule_key = schedule[station][s]
                title = append_asterisk(title, schedule_key)
                file_handle.write(f'\t\t<title lang="{lang}">{title}</title>\n')

            episode_in_program = 'episode' in programs[program]
            movie_year_in_program = ('M' in options and 'movie_year' in programs[program])
            if episode_in_program:
                if programs[program]['episode'] is not None:
                    file_handle.write(f'\t\t<sub-title lang="{lang}">')
                    file_handle.write(encode_lcl(programs[program]['episode']))
                    file_handle.write('</sub-title>\n')
            elif movie_year_in_program:
                    file_handle.write(f'\t\t<sub-title lang="{lang}">')
                    file_handle.write(f'Movie ({programs[program]["movie_year"]})')
                    file_handle.write('</sub-title>\n')


            if 'description' in programs[program]:
                if programs[program]['description'] is not None:
                    encoded_description = encode_lcl(programs[program]["description"])
                    file_handle.write(f'\t\t<desc lang="{lang}">{encoded_description}</desc>\n')
            
            if any(key in programs[program] for key in ['actor', 'director', 'writer', 'producer', 'presenter']):
                #print(f'key is {key}')
                file_handle.write('\t\t<credits>\n')
                if 'director' in programs[program]:
                    print_credits(file_handle, program, "director")
                if 'actor' in programs[program]:
                    for actor in sorted(programs[program]['actor'].keys(), key=lambda a: programs[program]['actor'][a]):
                        file_handle.write(f'\t\t\t<actor')
                        if 'role' in programs[program] and 'actor' in programs[program]['role']:
                            file_handle.write(f' role="{encode_lcl(programs[program]["role"][actor])}"')
                        file_handle.write(f'>{encode_lcl(actor)}</actor>\n')
                if 'writer' in programs[program]:                        
                    print_credits(file_handle, program, "writer")
                if 'producer' in programs[program]:                        
                    print_credits(file_handle, program, "producer")
                if 'presenter' in programs[program]:                        
                    print_credits(file_handle, program, "presenter")
                file_handle.write('\t\t</credits>\n')

            date = None
            # print(f"check program date {program}")
            if 'originalAirDate' in programs[program]:
                # print(f'print program {programs[program]}')
                # print(f"check program date {programs[program]['originalAirDate']}")
                
                date = convert_oad(programs[program]['originalAirDate'])
            # else:
            #    print(f"'originalAirDate' not in programs")

            if 'movie_year' in programs[program]:
                if programs[program]['movie_year'] is not None:
                    date = programs[program]['movie_year']
                    # print(f"set date {date}")
            elif 'originalAirDate' in programs[program] and (program.startswith('EP') or program[0].isdigit()):
                print(f"set original air date")
                date = convert_oad(programs[program]['originalAirDate'])

            if date is not None:
                # print(f"output date")
                file_handle.write(f'\t\t<date>{date}</date>\n')

            if 'genres' in programs[program]:
                for genre in sorted(programs[program]['genres'].keys(), key=lambda g: (programs[program]['genres'][g], g)):
                    file_handle.write(f'\t\t<category lang="{lang}">{encode_lcl(genre.capitalize())}</category>\n')

            if 'duration' in programs[program]:
                file_handle.write(f'\t\t<length units="minutes">{programs[program]["duration"]}</length>\n')

            if 'imageUrl' in programs[program]:
                file_handle.write(f'\t\t<icon src="{encode_lcl(programs[program]["imageUrl"])}" />\n')

            if 'url' in programs[program]:
                file_handle.write(f'\t\t<url>{encode_lcl(programs[program]["url"])}</url>\n')

            xml_season_number = None
            xml_episode_number = None

            if 'seasonNum' in programs[program] and 'episodeNum' in programs[program]:
                season_number = programs[program]['seasonNum']
                if season_number is not None:
                    xml_season_number = int(season_number) - 1
                    season_format = f"S{int(season_number):02d}"
                episode_number = programs[program]['episodeNum']
                if episode_number is not None:
                    xml_episode_number = int(episode_number) - 1
                    episode_format = f"E{int(episode_number):02d}"


                if season_number is not None:
                    if int(season_number) > 0 or int(episode_number) > 0:
                        file_handle.write(f'\t\t<episode-num system="common">{season_format}{episode_format}</episode-num>\n')

            dd_prog_id = program
            if re.match(r'^(..\d{8})(\d{4})', dd_prog_id):
                # print(f'dd_prog_id = {dd_prog_id}')
                dd_prog_id = f"{dd_prog_id[:10]}.{dd_prog_id[10:]}"
                file_handle.write(f'\t\t<episode-num system="dd_progid">{dd_prog_id}</episode-num>\n')
            if xml_season_number is not None and xml_episode_number is not None and int(xml_season_number) >= 0 and int(xml_episode_number) >= 0:
                file_handle.write(f"\t\t<episode-num system=\"xmltv_ns\">{xml_season_number}.{xml_episode_number}.</episode-num>\n")

            if 'quality' in schedule[station][s]:
                if schedule[station][s]['quality'] is not None:
                    file_handle.write("\t\t<video>\n")
                    file_handle.write("\t\t\t<aspect>16:9</aspect>\n")
                    file_handle.write("\t\t\t<quality>HDTV</quality>\n")
                    file_handle.write("\t\t</video>\n")

            is_new = schedule[station][s].get('new') is not None
            is_live = schedule[station][s].get('live') is not None
            has_cc = schedule[station][s].get('cc') is not None

            if not is_new and not is_live and (program.startswith('EP') or program.startswith('SH') or program[0].isdigit()):
                file_handle.write("\t\t<previously-shown ")
                if 'originalAirDate' in programs[program]:
                    date = convert_oad(programs[program]['originalAirDate'])
                    file_handle.write(f'start="{date}000000" ')
                file_handle.write("/>\n")

            if 'premiere' in schedule[station][s]:
                file_handle.write(f"\t\t<premiere>{schedule[station][s]['premiere']}</premiere>\n")

            if 'finale' in schedule[station][s]:
                file_handle.write(f"\t\t<last-chance>{schedule[station][s]['finale']}</last-chance>\n")

            if is_new:
                file_handle.write("\t\t<new />\n")
            # not part of XMLTV format yet?
            if 'L' in options and is_live:
                file_handle.write("\t\t<live />\n")
            if has_cc:
                file_handle.write("\t\t<subtitles type=\"teletext\" />\n")

            if 'rating' in programs[program]:
                file_handle.write("\t\t<rating>\n\t\t\t<value>{}</value>\n\t\t</rating>\n".format(programs[program]['rating']))

            if 'starRating' in programs[program]:
                file_handle.write("\t\t<star-rating>\n\t\t\t<value>{}/4</value>\n\t\t</star-rating>\n".format(programs[program]['starRating']))
            file_handle.write("\t</programme>\n")
            index += 1
        
def print_header_xtvd(file_handle, encoding):
    file_handle.write("<?xml version='1.0' encoding='{}'?>\n".format(encoding))
    file_handle.write("<xtvd from='{}' to='{}' schemaVersion='1.3' xmlns='urn:TMSWebServices' xmlns:xsi='http://www.w3.org/2001/XMLSchema-instance' xsi:schemaLocation='urn:TMSWebServices http://docs.tms.tribune.com/tech/xml/schemas/tmsxtvd.xsd'>\n".format(conv_time_xtvd(XTVD_startTime), conv_time_xtvd(XTVD_endTime)))

def print_credits(file_handle, program, string):
    for group in sorted(programs[program][string].keys(), key=lambda g: programs[program][string][g]):
        file_handle.write("\t\t\t<{}>{}</{}>\n".format(string, encode_lcl(group), string))

def print_footer_xtvd(file_handle):
    file_handle.write("</xtvd>\n")

def print_stations_xtvd(file_handle):
    file_handle.write("<stations>\n")
    for key in sorted(stations.keys(), key=sort_chan):
        file_handle.write("\t<station id='{}'>\n".format(stations[key]['stnNum']))
        if 'number' in stations[key]:
            station_name = encode_lcl(stations[key]['name'])
            file_handle.write("\t\t<callSign>{}</callSign>\n".format(station_name))
            file_handle.write("\t\t<name>{}</name>\n".format(station_name))
            file_handle.write("\t\t<fccChannelNumber>{}</fccChannelNumber>\n".format(stations[key]['number']))
            copy_logo(key)
        file_handle.write("\t</station>\n")
    file_handle.write("</stations>\n")

def print_lineups_xtvd(file_handle):
    file_handle.write("<lineups>\n")
    file_handle.write("\t<lineup id='{}' name='{}' location='{}' type='{}' postalCode='{}'>\n".format(lineupId, lineupname, lineuplocation, lineuptype, postalcode))
    for key in sorted(stations.keys(), key=sort_chan):
        if 'number' in stations[key]:
            file_handle.write("\t<map station='{}' channel='{}'></map>\n".format(stations[key]['stnNum'], stations[key]['number']))
    file_handle.write("\t</lineup>\n")
    file_handle.write("</lineups>\n")

def print_schedules_xtvd(file_handle):
    print(file_handle, "<schedules>")
    for station in sorted(stations.keys()):
        index = 0
        key_array = sorted(schedule[station].keys(), key=lambda x: schedule[station][x]['time'])
        for schedule_key in key_array:
            if len(key_array) <= index:
                del schedule[station][schedule_key]
                continue
            program = schedule[station][schedule_key]['program']
            start_time = conv_time_xtvd(schedule[station][schedule_key]['time'])
            stop_time = conv_time_xtvd(schedule[station][key_array[index + 1]]['time'])
            duration = conv_duration_xtvd(schedule[station][key_array[index + 1]]['time'] - schedule[station][schedule_key]['time'])

            print(file_handle, f"\t<schedule program='{program}' station='{stations[station]['stnNum']}' time='{start_time}' duration='{duration}'", end='')
            if 'quality' in schedule[station][schedule_key]:
                print(file_handle, " hdtv='true'", end='')
            if 'new' in schedule[station][schedule_key] or 'live' in schedule[station][schedule_key]:
                print(file_handle, " new='true'", end='')
            print(file_handle, "/>")
            index += 1
    print(file_handle, "</schedules>")

def print_programs_xtvd(file_handle):
    print(file_handle, "<programs>")
    for program_id in programs.keys():
        print(file_handle, f"\t<program id='{program_id}'>")
        if 'title' in programs[program_id]:
            print(file_handle, f"\t\t<title>{encode_lcl(programs[program_id]['title'])}</title>")
        if 'episode' in programs[program_id]:
            print(file_handle, f"\t\t<subtitle>{encode_lcl(programs[program_id]['episode'])}</subtitle>")
        if 'description' in programs[program_id]:
            print(file_handle, f"\t\t<description>{encode_lcl(programs[program_id]['description'])}</description>")
        
        if 'movie_year' in programs[program_id]:
            print(file_handle, f"\t\t<year>{programs[program_id]['movie_year']}</year>")
        else:  # Guess
            show_type = "Series"
            if 'Paid Programming' in programs[program_id]['title']:
                show_type = "Paid Programming"
            print(file_handle, f"\t\t<showType>{show_type}</showType>")
            print(file_handle, f"\t\t<series>EP{program_id[2:10]}</series>")
            if 'originalAirDate' in programs[program_id]:
                print(file_handle, f"\t\t<originalAirDate>{conv_oadtv(programs[program_id]['originalAirDate'])}</originalAirDate>")
        print(file_handle, "\t</program>")
    print(file_handle, "</programs>")

def print_genres_xtvd(file_handle):
    file_handle.write("<genres>\n")
    for program_key in programs.keys():
        if 'genres' in programs[program_key] and programs[program_key]['genres'].get('movie') != 1:
            file_handle.write(f"\t<programGenre program='{program_key}'>\n")
            for genre_key in programs[program_key]['genres'].keys():
                file_handle.write("\t\t<genre>\n")
                file_handle.write(f"\t\t\t<class>{encode_lcl(genre_key.capitalize())}</class>\n")
                file_handle.write("\t\t\t<relevance>0</relevance>\n")
                file_handle.write("\t\t</genre>\n")
            file_handle.write("\t</programGenre>\n")
    file_handle.write("</genres>\n")

def getZapGParams():
    hash_map = get_zap_params()
    hash_map['country'] = hash_map.pop('countryCode', None)
    return "&".join(f"{key}={value}" for key, value in hash_map.items())

def getZapPParams():
    parameters = get_zap_params()
    parameters.pop('lineupId', None)
    return parameters

def get_zap_params():
    global postalcode
    global lineupId
    country = "USA"
    device = ""
    result_hash = {}
    print(f'postalcode is {postalcode}')

    if zlineupId is not None or zipcode is not None:
        postalcode = zipcode
        if re.search(r'[A-z]', zipcode):
            country = "CAN"
        if ':' in zlineupId:
            lineupId, device = zlineupId.split(':')
        else:
            lineupId = zlineupId
        
        result_hash['postalCode'] = postalcode
    else:
        result_hash['token'] = get_z_token()

    result_hash['postalCode'] = postalcode
    result_hash['countryCode'] = country
    result_hash['headendId'] = lineupId
    result_hash['device'] = device
    result_hash['aid'] = 'gapzap'
    result_hash['lineupId'] = f"{country}-{lineupId}-DEFAULT"

    
    return result_hash

def ua_stats(requests_session: requests.Session, request_method, *params):
    global total_requests
    global total_bytes
    request_response = None
    # print(f"Call requests_session.get with params {params} ")
    if request_method == 'POST':
        request_response = requests_session.post(*params)
    else:
        # print(f"Call requests_session.get with {requests_session} ")
        request_response = requests_session.get(*params)

    #connection_cache = user_agent.conn_cache
    #if connection_cache is not None:
    #    connections = connection_cache.get_connections()
    #    for connection in connections:
    #        tcp_sockets[connection] = 1

    total_requests += 1
    total_bytes += len(request_response.content)
    return request_response

def ua_get(requests_session: requests.Session, *params):
    return ua_stats(requests_session, 'GET', *params)


def ua_post(requests_session: requests.Session, *params):
    return ua_stats(requests_session, 'POST', *params)


def getURL(url, error_flag, requests_session: requests.Session):
    import time
    global logged_in
    print(f'url is {url}')

    if (logged_in == False):
        login(requests_session)
        logged_in = True

    print(f'requests_session is {requests_session}')

    retry_count = 0
    retries = 1
    while retry_count < retries:
        pout(f"[{total_requests}] Getting: {url}\n")
        time.sleep(sleeptime)  # do these rapid requests flood servers?
        response = ua_get(requests_session, url)
        # response.encoding = 'utf-8'
        content_length = len(response.content)
        try:
            decoded_content = response.content.decode('utf-8', errors='replace')
        except UnicodeDecodeError as e:
            print(f"Decoding error: {e}")
            
        if (response.status_code == 200) and content_length:
            return decoded_content
        elif response.status_code == 500 and "Could not load details" in decoded_content:
            pout(f"{decoded_content}\n")
            return ""
        else:
            log_warning(f"[Attempt {retry_count + 1}] {content_length}: {response.status_code}\n")
            log_warning(f"{response.content}\n")
            time.sleep(sleeptime + 2)
        retry_count += 1

    log_warning(f"Failed to download within {retries} retries.\n")
    if error_flag:
        log_warning("Server out of data? Temporary server error? Normal exit anyway.\n")
        return ""
    raise Exception

import os
import shutil

def write_binary_file(file_path, content):
    with open(file_path, 'wb') as file:
        file.write(content)

def delete_file(file_path):
    try:
        os.remove(file_path)
    except OSError as e:
        print(f"Failed to delete '{file_path}': {e}")

def copy_logo(key):
    cid = key
    if cid not in logos or 'logo' not in logos[cid]:
        cid = key.split('.')[-1]
    if 'iconDir' in globals() and cid in logos and 'logo' in logos[cid]:
        num = stations[key]['number']
        src = f"{iconDir}/{logos[cid]['logo']}{logos[cid]['logoExt']}"
        dest1 = f"{iconDir}/{num}{logos[cid]['logoExt']}"
        dest2 = f"{iconDir}/{num} {stations[key]['name']}{logos[cid]['logoExt']}"
        dest3 = f"{iconDir}/{num}_{stations[key]['name']}{logos[cid]['logoExt']}"
        shutil.copy(src, dest1)
        shutil.copy(src, dest2)
        shutil.copy(src, dest3)

def handle_logo(url):
    if not os.path.exists(iconDir):
        os.makedirs(iconDir)
    name, _, extension = os.path.splitext(os.path.basename(url))
    stations[cs]['logoURL'] = url
    logos[cs]['logo'] = name
    logos[cs]['logoExt'] = extension
    file_path = os.path.join(iconDir, f"{name}{extension}")
    if not os.path.exists(file_path):
        write_binary_file(file_path, getURL(url, 0))

def set_original_air_date():
    # print(f'set original air date for cp {cp}')
    if cp[10:14] != '0000':
        # print(f'set original air date passed check')
        if cp not in programs or 'originalAirDate' not in programs[cp] or schedule[cs][sch]['time'] < programs[cp]['originalAirDate']:
            # print(f'set original air date for cp {cp}')
            return True
            #programs[cp]['originalAirDate'] = schedule[cs][sch]['time']
    return False
    
import json

def get_z_token():
    global zapToken
    if zapToken is None:
        login(requests_session)
    return zapToken

def parse_tvg_favs(buffer):
    data = json.loads(buffer)
    if 'message' in data:
        messages = data['message']
        for item in messages:
            source = item["source"]
            channel = item["channel"]
            tvgfavs[f"{channel}.{source}"] = 1
        pout("Lineup " + zlineupId + " favorites: " + ', '.join(tvgfavs.keys()) + "\n")

def parse_tvg_icons(tvgspritesurl, zlineupId, icon_dir):
    response_content = requests.get(tvgspritesurl + f"{zlineupId}.css").content.decode('utf-8')
    
    match = re.search(r'background-image:.+?url\((.+?)\)', response_content)
    if match:
        url = tvgspritesurl + match.group(1)

        if not os.path.isdir(icon_dir):
            os.makedirs(icon_dir)

        filename, file_extension = os.path.splitext(os.path.basename(url))
        file_path = os.path.join(icon_dir, f"sprites-{filename}{file_extension}")
        with open(file_path, 'wb') as file:
            file.write(requests.get(url).content)

        image = Image.open(file_path).convert("RGBA")

        icon_width = 30
        icon_height = 20
        for match in re.finditer(r'listings-channel-icon-(.+?)\{.+?position:.*?\-(\d+).+?(\d+).*?\}', response_content, re.DOTALL):
            channel_id = match.group(1)
            icon_x = int(match.group(2))
            icon_y = int(match.group(3))

            icon = Image.new("RGBA", (icon_width, icon_height))
            icon.paste(image.crop((icon_x, icon_y, icon_x + icon_width, icon_y + icon_height)), (0, 0))

            logos[channel_id] = {}
            logos[channel_id]['logo'] = f"sprite-{channel_id}"
            logos[channel_id]['logoExt'] = file_extension

            icon_file_name = os.path.join(icon_dir, f"{logos[channel_id]['logo']}{logos[channel_id]['logoExt']}")
            icon.save(icon_file_name, format='PNG')
        
import json
import gzip

def parse_tv_gd(file_path):
    with gzip.open(file_path, "rb") as gz_file:
        buffer = gz_file.read()
    
    data = json.loads(buffer)

    if 'program' in data:
        program_data = data['program']
        if 'release_year' in program_data:
            programs[cp]['movie_year'] = program_data['release_year']
        if 'rating' in program_data and 'rating' not in programs[cp]:
            if program_data['rating'] != 'NR':
                programs[cp]['rating'] = program_data['rating']

    if 'tvobject' in data:
        tv_object = data['tvobject']
        if 'photos' in tv_object:
            photos = tv_object['photos']
            photo_hash = {}
            for photo in photos:
                width = photo['width']
                height = photo['height']
                url = photo['url']
                photo_hash[width * height] = url
            
            largest_photo = max(photo_hash.keys())
            programs[cp]['imageUrl'] = photo_hash[largest_photo]

import gzip
import json

def parse_tvg_grid(file_path):
    with gzip.open(file_path, "rb") as gz_file:
        buffer = gz_file.read()
    
    tvg_data = json.loads(buffer)

    for entry in tvg_data:
        channel_info = entry['Channel']
        source_id = channel_info['SourceId']
        channel_number = channel_info['Number']

        channel_key = f"{channel_number}.{source_id}"

        if tvgfavs:
            if channel_key not in tvgfavs:
                continue

        if channel_key not in stations:
            stations[channel_key] = {
                'stnNum': source_id,
                'number': channel_number,
                'name': channel_info['Name']
            }
            if 'FullName' in channel_info and channel_info['FullName'] != channel_info['Name']:
                if channel_info['FullName']:
                    stations[channel_key]['fullname'] = channel_info['FullName']

            if 'order' not in stations[channel_key]:
                if 'b' in options:
                    stations[channel_key]['order'] = co_num
                    co_num += 1
                else:
                    stations[channel_key]['order'] = stations[channel_key]['number']

        program_schedules = entry['ProgramSchedules']
        for program_entry in program_schedules:
            if 'ProgramId' not in program_entry:
                continue
            
            program_id = program_entry['ProgramId']
            category_id = program_entry['CatId']

            if category_id == 1:
                programs[program_id]['genres']['movie'] = 1
            elif category_id == 2:
                programs[program_id]['genres']['sports'] = 1
            elif category_id == 3:
                programs[program_id]['genres']['family'] = 1
            elif category_id == 4:
                programs[program_id]['genres']['news'] = 1

            parent_program_id = program_entry.get('ParentProgramId')
            if (parent_program_id is not None and parent_program_id != 0) or ('j' in options and category_id != 1):
                programs[program_id]['genres']['series'] = 99

            programs[program_id]['title'] = program_entry['Title']
            tba_flag = 1 if re.search(sTBA, programs[program_id]['title'], re.IGNORECASE) else 0

            if 'EpisodeTitle' in program_entry and program_entry['EpisodeTitle']:
                programs[program_id]['episode'] = program_entry['EpisodeTitle']
                tba_flag = 1 if re.search(sTBA, programs[program_id]['episode'], re.IGNORECASE) else 0

            if 'CopyText' in program_entry and program_entry['CopyText']:
                programs[program_id]['description'] = program_entry['CopyText']
            if 'Rating' in program_entry and program_entry['Rating']:
                programs[program_id]['rating'] = program_entry['Rating']

            schedule_time = program_entry['startTime'] * 1000
            schedule[channel_key][schedule_time] = {
                'time': schedule_time,
                'endtime': program_entry['endTime'] * 1000,
                'program': program_id,
                'station': channel_key
            }

            airing_attributes = program_entry['AiringAttrib']
            if airing_attributes & 1:
                schedule[channel_key][schedule_time]['live'] = 1
            elif airing_attributes & 4:
                schedule[channel_key][schedule_time]['new'] = 1

            tv_object = program_entry.get('TVObject')
            if tv_object:
                if 'SeasonNumber' in tv_object and tv_object['SeasonNumber'] != 0:
                    programs[program_id]['seasonNum'] = tv_object['SeasonNumber']
                    if 'EpisodeNumber' in tv_object and tv_object['EpisodeNumber'] != 0:
                        programs[program_id]['episodeNum'] = tv_object['EpisodeNumber']
                if 'EpisodeAirDate' in tv_object:
                    episode_air_date = tv_object['EpisodeAirDate']
                    episode_air_date = ''.join(filter(str.isdigit, episode_air_date))
                    if episode_air_date:
                        programs[program_id]['originalAirDate'] = episode_air_date
                url = tv_object.get('EpisodeSEOUrl') or tv_object.get('SEOUrl')
                if url and category_id == 1 and 'movies' not in url:
                    url = f"/movies{url}"
                if url:
                    programs[program_id]['url'] = tvgurl[:-1] + url

            if ('I' in options or
                ('D' in options and programs[program_id]['genres'].get('movie')) or
                ('W' in options and programs[program_id]['genres'].get('movie'))):
                get_details(parse_tvg_d, program_id, f"{tvgMapiRoot}listings/details?program={program_id}", "")

def get_details(func, cp, url, prefix):
    fn = f"{cacheDir}/{prefix}{cp}.js.gz"
    if not os.path.exists(fn):
        response = getURL(url, 1)
        if len(response):
            encoded_response = response.encode('utf8')
            write_binary_file(fn, zlib.compress(encoded_response))
    if os.path.exists(fn):
        l = prefix if len(prefix) else "D"
        pout(f"[{l}] Parsing: {cp}\n")
        func(fn)
    else:
        pout(f"Skipping: {cp}\n")

def parse_json(filename):
    global cp
    global cs
    global sch
    decoded_content = None
    with gzip.open(filename, 'rt') as f:
    # gz = gzip.open(filename, "rb")
    # buffer = b""
    # while True:
    #    data = gz.read(65535)
    #    if not data:
    #        break
    #    buffer += data
    # gz.close()
    #json_data = json.loads(buffer)
    #print (f'json_data {json_data}')

        content = f.read()

    json_data = json.loads(content)
    stations_list = json_data['channels']
    zap_starred = {}
    for station in stations_list:
        if 'channelId' in station:
            if not allChan and len(zapFavorites) > 0:
                if zapFavorites.get(station['channelId']):
                    if options.get(8):
                        if zap_starred.get(station['channelId']):
                            continue
                        zap_starred[station['channelId']] = 1
                else:
                    continue

            cs = f"{station['channelNo']}.{station['channelId']}"
            stations[cs] = {
                'stnNum': station['channelId'],
                'name': station['callSign'],
                'number': station['channelNo'].lstrip('0')
            }

            if 'order' not in stations[cs]:
                if 'b' in options:
                    stations[cs]['order'] = coNum[0]
                    coNum[0] += 1
                else:
                    stations[cs]['order'] = stations[cs]['number']

            if station['thumbnail']:
                url = station['thumbnail']
                url = url.split('?')[0]  # remove size
                if not url.startswith('http'):
                    url = "https:" + url
                stations[cs]['logoURL'] = url
                if iconDir != None:
                    handle_logo(url)

            events = station['events']
            for event in events:
                program = event['program']
                cp = program['id']

                # print(f'event is {event}')
                
                duration = event.get('duration', 0)
                    
                programs[cp] = {
                    'title': program['title'],
                    'episode': program.get('episodeTitle', ''),
                    'description': program.get('shortDesc', ''),
                    'duration': duration,
                    'movie_year': program.get('releaseYear', ''),
                    'seasonNum': program.get('season', ''),
                    'episodeNum': program.get('episode', '')
                }

                if event['thumbnail']:
                    turl = f"{urlAssets}{event['thumbnail']}.jpg"
                    programs[cp]['imageUrl'] = turl

                if program.get('seriesId') and program.get('tmsId'):
                    programs[cp]['url'] = f"{urlRoot}overview-affiliates.html?programSeriesId={program['seriesId']}&tmsId={program['tmsId']}"

                # print(f'starttime is {event['startTime']}')
                sch = str2time1(event['startTime']) * 1000
                # print(f'cp is {program['title']}')
                # print(f'sch is {sch}')

                if cs not in schedule:
                     schedule[cs] = {}
                schedule[cs][sch] = {
                    'time': sch,
                    'endtime': str2time1(event['endTime']) * 1000,
                    'program': cp,
                    'station': cs
                }

                # print(f'schedule[cs][sch]["endtime"] is {schedule[cs][sch]["endtime"]}')

                if 'filter' in event:
                    genres = event['filter']
                    for i, g in enumerate(genres, start=1):
                        g = g.replace('filter-', '', 1)
                        programs[cp].setdefault('genres', {})[g.lower()] = i

                if 'rating' in event:
                    # print(f"event is {event}")
                    # print(f"event['rating'] is {event['rating']}")
                    if event['rating'] != None:
                        programs[cp]['rating'] = event['rating']

                if 'tags' in event:
                    tags = event['tags']
                    if 'CC' in tags:
                        schedule[cs][sch]['cc'] = 1

                if 'flag' in event:
                    flags = event['flag']
                    # print(f'flags are {flags}')
                    if 'New' in flags:
                        schedule[cs][sch]['new'] = 'New'
                        if set_original_air_date():
                            programs[cp]['originalAirDate'] = schedule[cs][sch]['time']
                            # print(f"programs[cp]['originalAirDate'] is {programs[cp]['originalAirDate']}")
                    if 'Live' in flags:
                        schedule[cs][sch]['live'] = 'Live'
                        if set_original_air_date():  # live to tape?
                            programs[cp]['originalAirDate'] = schedule[cs][sch]['time']
                    if 'Premiere' in flags:
                        schedule[cs][sch]['premiere'] = 'Premiere'
                    if 'Finale' in flags:
                        schedule[cs][sch]['finale'] = 'Finale'

                if 'D' in options and (program.get('isGeneric') is not None):
                    post_json_overview(cp, program['seriesId'])
                if 'j' in options and not cp.startswith('MV'):
                    programs[cp].setdefault('genres', {})['series'] = 99

    return 0


def post_json_overview(cp, sid):
    import time
    global programs
    fn = f"{cacheDir}/O{cp}.js.gz"

    print(f'In post_json_overview')
    if not os.path.exists(fn) and sid in sidCache and os.path.exists(sidCache[sid]):
        shutil.copy(sidCache[sid], fn)
    
    if not os.path.exists(fn):
        url = urlRoot + 'api/program/overviewDetails'
        pout(f"[{total_requests}] Post {sid}: {url}\n")
        time.sleep(sleeptime)  # do these rapid requests flood servers?
        param_hash = get_zap_params()
        param_hash['programSeriesID'] = sid
        param_hash['clickstream[FromPage]'] = 'TV%20Grid'
        response = ua_post(requests_session, url, param_hash)
        

        if response.status_code == 200:
            decoded_content = response.content.decode('utf8')
            encoded_content = decoded_content.encode('utf8')
            compressor = compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
            compressed_data = compressor.compress(encoded_content)
            compressed_data += compressor.flush()
            write_binary_file(fn, compressed_data)
            sidCache[sid] = fn
        else:
            log_warning(f"{id}: {response.status_code}")

    if os.path.exists(fn):
        pout(f"[D] Parsing: {cp}\n")
        with gzip.open(fn, "rb") as gz:
            buffer = gz.read()
        t = json.loads(buffer)
        # print(f't is {t}')
        # exit(0)

        if t['seriesGenres'] != '':
            i = 2
            if 'genres'in programs[cp]:
                genre_hash = programs[cp]['genres']
                if genre_hash:
                    gen_arr = sorted(genre_hash, key=genre_hash.get)
                    max_genre = gen_arr[-1]
                    i = genre_hash[max_genre] + 1
                for sg in map(str.lower, t['seriesGenres'].split('|')):
                    if sg not in programs[cp]['genres']:
                        programs[cp]['genres'][sg] = i
                        i += 1

        i = 1
        for cast_member in t['overviewTab']['cast']:
            name = cast_member['name']
            character_name = cast_member['characterName']
            role = cast_member['role'].lower()
            if role == 'host':
                if 'presenter' not in programs[cp]:
                    programs[cp]['presenter'] = {}
                programs[cp]['presenter'][name] = i
                i += 1
            else:
                if 'actor' not in programs[cp]:
                    programs[cp]['actor'] = {}
                programs[cp]['actor'][name] = i
                if character_name:
                    programs[cp]['role'] = {}
                    programs[cp]['role'][name] = character_name
                i += 1

        i = 1
        for crew_member in t['overviewTab']['crew']:
            name = crew_member['name']
            role = crew_member['role'].lower()
            if 'producer' in role:
                if 'producer' not in programs[cp]:
                    programs[cp]['producer'] = {}
                programs[cp]['producer'][name] = i
            elif 'director' in role:
                if 'director' not in programs[cp]:
                    programs[cp]['director'] = {}
                programs[cp]['director'][name] = i
            elif 'writer' in role:
                if 'writer' not in programs[cp]:
                    programs[cp]['writer'] = {}
                programs[cp]['writer'][name] = i
            i += 1

        if 'imageUrl' not in programs[cp] and t['seriesImage'] != '':
            turl = urlAssets + t['seriesImage'] + ".jpg"
            programs[cp]['imageUrl'] = turl
            
        if re.match(r'^MV|^SH', cp):
            if (programs[cp]['description'] is None) or (len(t['seriesDescription']) > len(programs[cp]['description'])):
                programs[cp]['description'] = t['seriesDescription']
        
        if re.match(r'^EP', cp):  # GMT @ 00:00:00
            upcoming_episode = t['overviewTab'].get('upcomingEpisode')
            if upcoming_episode and upcoming_episode['tmsID'].lower() == cp.lower() and upcoming_episode['originalAirDate'] != '' and upcoming_episode['originalAirDate'] != '1000-01-01T00:00Z':
                oad = str2time2(upcoming_episode['originalAirDate'])
                oad *= 1000
                programs[cp]['originalAirDate'] = oad
            else:
                for upcoming in t['upcomingEpisodeTab']:
                    if upcoming['tmsID'].lower() == cp.lower() and upcoming['originalAirDate'] != '' and upcoming['originalAirDate'] != '1000-01-01T00:00Z':
                        oad = str2time2(upcoming['originalAirDate'])
                        oad *= 1000
                        programs[cp]['originalAirDate'] = oad
                        break
    else:
        pout(f"Skipping: {sid}\n")

from time import *
from datetime import datetime
import calendar

def str2time1(time_string):
    # print(f'time_string is {time_string}')
    utc_time = datetime.strptime(time_string, '%Y-%m-%dT%H:%M:%SZ')
    epoch_time = (utc_time - datetime(1970, 1, 1)).total_seconds()
    return int(epoch_time)

def str2time2(time_str):
    utc_time = datetime.strptime(time_str, '%Y-%m-%dT%H:%MZ')
    epoch_time = (utc_time - datetime(1970, 1, 1)).total_seconds()
    return int(epoch_time)    

def hour_to_millis(start, grid_hours):
    current_time = localtime(time())
    sec, min, hour, mday, mon, year = current_time.tm_sec, current_time.tm_min, current_time.tm_hour, current_time.tm_mday, current_time.tm_mon, current_time.tm_year + 1900
    if start == 0:
        hour = (hour // grid_hours) * grid_hours
    else:
        hour = 0
    time_in_seconds = calendar.timegm((year, mon, mday, hour, 0, 0))
    time_in_seconds -= tz_offset() * 3600
    gm_time = gmtime(time_in_seconds)
    time_in_seconds = calendar.timegm((gm_time.tm_year + 1900, gm_time.tm_mon + 1, gm_time.tm_mday, gm_time.tm_hour, gm_time.tm_min, gm_time.tm_sec))
    return str(time_in_seconds) + "000"

def tz_offset(n=None):
    if n is None:
        n = time()
    local_time = localtime(n)
    gm_time = gmtime(n)
    return (local_time.tm_min - gm_time.tm_min) / 60 + local_time.tm_hour - gm_time.tm_hour + 24 * (local_time.tm_year - gm_time.tm_year)

def timezone(tztime=None):
    if tztime is None:
        tztime = time()
    tztime_secs = int(tztime/1000)
    os = (calendar.timegm(localtime(tztime_secs)) - tztime_secs) / 3600
    mins = abs(os - int(os)) * 60
    return f"{int(os):+03d}{int(mins):02d}"

def max_value(a, b):
    return a if a > b else b

def min_value(a, b):
    return a if a < b else b


if cacheDir != None:
    if not os.path.isdir(cacheDir):
        os.mkdir(cacheDir)
    else:
        with os.scandir(cacheDir) as entries:
            cacheFiles = [entry.name for entry in entries if entry.is_file() and (entry.name.endswith('.html') or entry.name.endswith('.js'))]
        
        for cacheFile in cacheFiles:
            fn = os.path.join(cacheDir, cacheFile)
            atime = os.path.getatime(fn)
            if atime + ((days + 2) * 86400) < time.time():
                pout(f"Deleting old cached file: {fn}\n")
                delete_file(fn)

#s1 = time.perf_counter()
s1 = 0


def parse_z_favs(buffer):
    data = json.loads(buffer)
    if 'channels' in data:
        channels = data['channels']
        for channel in channels:
            #if options['R']:
            #    response = ua_post(urlRoot + "api/user/ChannelAddtofav", 
            #                       {'token': zap_token, 'prgsvcid': channel, 'addToFav': "false"}, 
            #                       headers={'X-Requested-With': 'XMLHttpRequest'})
            #    if response.is_success:
            #        pout(f"Removed favorite {channel}\n")
            #    else:
            #        log_warning("RF" + response.status_line + "\n")
            #else:
            zapFavorites[channel] = 1
        #if options['R']:
        #    pout("Removed favorites, exiting\n")
        #    exit()
        pout("Lineup favorites: " + ', '.join(zapFavorites.keys()) + "\n")

def login_zap(requests_session: requests.Session):
    retry_count = 0
    retries = 3
    global postalcode
    global country
    global lineupId
    global device
    global zapToken
    global zapPref

    while retry_count < retries:
        print(f'login userEmail is {userEmail}')
        print(f'login password is {password}')

        json_auth={
            'emailid': userEmail,
            'password': password,
            'usertype': '0',
            'facebookuser': 'false'
        }

        response = requests_session.post(urlRoot + 'api/user/login', json_auth)

        # requests_session.auth = json_auth
        print(f'login response is {response}')
        print(f'Session is  {requests_session}')

        decoded_content = response.content.decode('utf-8')
        if response.ok:
            response_data = json.loads(decoded_content)
            zapToken = response_data['token']
            # print(f'zapToken is {zapToken}')
            zapPref = ''
            if response_data.get('isMusic'):
                zapPref += "m"
            if response_data.get('isPPV'):
                zapPref += "p"
            if response_data.get('isHD'):
                zapPref += "h"
            if zapPref == '':
                zapPref = '-'
            else:
                zapPref = ','.join(zapPref)

            requests_session.headers['Authorization'] = f'Bearer {zapToken}'
            properties = response_data['properties']
            print(properties)
        
            postalcode = properties["2002"]
            country = properties["2003"]
            lineupId, device = properties["2004"].split(':')

            if 'a' not in options:
                print("Requesting Favorites")
                favorites_response = requests_session.post(urlRoot + "api/user/favorites", json={'token': zapToken}, headers={'X-Requested-With': 'XMLHttpRequest'})
                favorites_decoded_content = favorites_response.content.decode('utf-8')
                if favorites_response.ok:
                    parse_z_favs(favorites_decoded_content)
                else:
                    log_warning(f"FF{favorites_response.status_code}: {favorites_decoded_content}\n")

            return decoded_content
        else:
            pout(f"[Attempt {retry_count + 1}] {decoded_content}\n")
            time.sleep(sleeptime + 1)
            retry_count += 1

    raise Exception(f"Failed to login within {retries} retries.\n")

def hour_to_milliseconds():
    import time
    from time import gmtime, strftime
    
    current_time = time.localtime()
    year = current_time.tm_year
    month = current_time.tm_mon
    hours = current_time.tm_hour
    day_of_month = current_time.tm_mday
    is_dst = current_time.tm_isdst
    #seconds, minutes, hours, day_of_month, month, year, weekday, day_of_year, is_dst = current_time
    
    if start == 0:
        hours = int(hours / gridHours) * gridHours
    else:
        hours = 0
    '''
    print(f'hours is {hours}')
    print(f'gridHours is {gridHours}')
    print(f'year is {year}')
    print(f'month is {month}')
    print(f'day_of_month is {day_of_month}')
    '''

    t = time.mktime((year, month, day_of_month, hours, 0, 0, 0, 0, is_dst))
    return t*1000

def login(requests_session: requests.Session):
    import time
    if userEmail is None or userEmail == '' or password is None or password == '':
        if zlineupId is None:
            raise Exception("Unable to login: Unspecified username or password.\n")
        

        '''
        user_agent = UserAgent(ssl_opts={'verify_hostname': False})  # WIN
        user_agent = UserAgent()  # WIN
        #user_agent.conn_cache = ConnCache(total_capacity=None)
        #user_agent.cookie_jar = Cookies()
        if proxy is not None:
            user_agent.proxy(['http', 'https'], proxy)
        user_agent.agent = 'Mozilla/4.0'
        #user_agent.default_headers.push_header('Accept-Encoding', 'gzip, deflate')
        user_agent.default_headers = {
            'User-Agent': user_agent.random,
            'Accept-Encoding': 'gzip, deflate'
        }
        '''
    if userEmail != '' and password != '':
        pout(f'Logging in as "{userEmail}" ({time.localtime()})\n')
        login_zap(requests_session)
    else:
        pout(f'Connecting with lineupId "{zlineupId}" ({time.localtime()})\n')
    

if 'z' in options:
    login(requests_session) if 'a' not in options else None  # get favorites
    parse_tvg_icons() if iconDir is not None else None
    gridHours = 3
    maxCount = days * int(24 / gridHours)
    offset = start * 3600 * 24 * 1000
    ms = hour_to_milliseconds() + offset

    for count in range(int(maxCount)):
        curday = int(count / (24 / gridHours)) + 1
        if count == 0:
            XTVD_startTime = ms
        elif count == maxCount - 1:
            XTVD_endTime = ms + (gridHours * 3600000) - 1

        fn = f"{cacheDir}/{ms}.js.gz"
        if not os.path.exists(fn) or curday > ncdays or curday <= ncsdays or curday == ncmday:
            login(requests_session) if 'zlineupId' not in locals() else None
            duration = gridHours * 60
            tvgstart = str(ms)[:-3]
            rs = getURL(f"{tvgurlRoot}Listingsweb/ws/rest/schedules/{zlineupId}/start/{tvgstart}/duration/{duration}", 1, requests_session)
            if rs == '':
                break
            rc = rs.encode('utf-8')
            with open(fn, 'wb') as f:
                f.write(zlib.compress(rc))
        pout(f"[{count + 1}/{maxCount}] Parsing: {fn}\n")
        parse_tvg_grid(fn)

        if 'T' in options and tba:
            pout(f"Deleting: {fn} (contains \"{sTBA}\")\n")
            delete_file(fn)
        if exp:
            pout(f"Deleting: {fn} (expired)\n")
            delete_file(fn)
        exp = 0
        tba = 0
        ms += (gridHours * 3600 * 1000)

else:

    login(requests_session) if 'a' not in options else None  # get favorites
    gridHours = 3
    print(f'days = {days}')

    print(f'hours = {int(24 / gridHours)}')
    hours = int(24.0 / gridHours)
    maxCount = days * hours
    print(f'maxCount = {maxCount}')
    offset = start * 3600 * 24 * 1000
    print(f'offset = {offset}')
    ms = int(hour_to_milliseconds() + offset)
    print(f'ms = {ms}')
    for count in range(int(maxCount)):
        curday = int(count / (24 / gridHours)) + 1
        if count == 0:
            XTVD_startTime = ms
        elif count == maxCount - 1:
            XTVD_endTime = ms + (gridHours * 3600000) - 1

        fn = f"{cacheDir}/{ms}.js.gz"
        if not os.path.exists(fn) or curday > ncdays or curday <= ncsdays or curday == ncmday:
            zstart = str(ms)[:-3]
            # print(f'zstart is {zstart}')
            params = f"?time={zstart}&timespan={gridHours}&pref={zapPref}&"
            params += getZapGParams()
            params += '&TMSID=&AffiliateID=gapzap&FromPage=TV%20Grid'
            params += '&ActivityID=1&OVDID=&isOverride=true'
            # print(f'params are {params}')
            # exit(0)
            print("getURL grid call")
            rs = getURL(f"{urlRoot}api/grid{params}", 1, requests_session)
            if rs == '':
                break
            rc = rs.encode('utf-8')
            with open(fn, 'wb') as f:
                compressor = compressor = zlib.compressobj(wbits=zlib.MAX_WBITS | 16)
                compressed_data = compressor.compress(rc)
                compressed_data += compressor.flush()
                f.write(compressed_data)

        pout(f"[{count + 1}/{maxCount}] Parsing: {fn}\n")
        parse_json(fn)

        if 'T' in options and tba:
            pout(f"Deleting: {fn} (contains \"{sTBA}\")\n")
            delete_file(fn)
        if exp:
            pout(f"Deleting: {fn} (expired)\n")
            delete_file(fn)
        exp = 0
        tba = 0
        ms += (gridHours * 3600 * 1000)




#s2 = time.perf_counter()
s2 = 0
tsockt = len(tsocks)
if total_bytes > 0:
    pout(f"Downloaded {pl(total_bytes, 'byte')} in {pl(total_requests, 'http request')} using {pl(tsockt if tsockt > 0 else total_requests, 'socket')}.\n")
if expired > 0:
    pout(f"Expired programs: {expired}\n")
pout(f"Writing XML file: {outFile}\n")

with open(outFile, 'w', encoding='utf-8') as FH:
    enc = 'ISO-8859-1'
    if 'U' in options:
        enc = 'UTF-8'
    
    if outputXTVD:
        print_header_xtvd
        print_stations_xtvd(FH)
        print_lineups_xtvd(FH)
        print_schedules_xtvd(FH)
        print_programs_xtvd(FH)
        print_genres_xtvd(FH)
        print_footer_xtvd(FH)
    else:
        print_header(FH, enc)
        print_channels(FH)
        #if 'includeXMLTV' in locals():
        #    pout(f"Reading XML file: {includeXMLTV}\n")
        #    incXML("<channel", "<programme", FH)
        print_programmes(FH)
        #if 'includeXMLTV' in locals():
        #    incXML("<programme", "</tv", FH)
        print_footer(FH)


ts = 0
for station in stations.keys():
    ts += len(schedule[station])

#s3 = time.perf_counter()
s3 = 0
pout(f"Completed in {s3 - s1:.2f}s (Parse: {s2 - s1:.2f}s) {len(stations)} stations, {len(programs)} programs, {ts} scheduled.\n")

if 'w' in options:
    input("Press ENTER to exit:")
else:
    if os.name == 'nt':
        time.sleep(3)

exit(0)
