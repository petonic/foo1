#! /usr/bin/env python3
#


import googlemaps
from datetime import datetime

PT_START = "6 noren way, pt reyes sta, ca"
PT_END = "fonda restaurant, albany, ca"
PT_WAYPT = "Golden Gate Bridge"

METERS_PER_MILE = 1609.34
SECS_PER_MIN = 60.0

gmaps = googlemaps.Client(key='AIzaSyAVn7Xdj26B6A33lTu6QSE9h0ACzl4YV4Q')

# Request directions via public transit

# directions_result = gmaps.directions("6 noren way, pt reyes sta, ca",
#                                      "fonda restaurant, albany, ca",
#                                      mode="driving",
#                                      departure_time=now)[0]


def get_drive_stats(*args):
    print('Stats for {}'.format(args))
    now = datetime.now()
    directions_result = gmaps.directions(
            *args, mode="driving", departure_time=now)[0]

    total_len = 0.0
    total_dur = 0.0

    legs = directions_result['legs']

    for i in legs:
        # print('#LEG = \n{}'.format(pprint.pformat(i, indent=4)))
        this_mins = i['duration_in_traffic']['value'] # Secs
        # print('**** mins = {}'.format(mins))
        this_len = i['distance']['value']             # Meters
        total_dur += this_mins
        total_len += this_len

    return (total_len, total_dur)


(str_len, str_dur) = get_drive_stats(PT_START, PT_END)

(wp1_len, wp1_dur) = get_drive_stats(PT_START, PT_WAYPT)
(wp2_len, wp2_dur) = get_drive_stats(PT_WAYPT, PT_END)

wp_tot_len = wp1_len + wp2_len
wp_tot_dur = wp1_dur + wp2_dur


print('Straight = {:1} min, {:1} miles'.format(
        str_dur / SECS_PER_MIN, str_len / METERS_PER_MILE))

print('WayPoint = {} min, {} miles'.format(
        wp_tot_dur / SECS_PER_MIN, wp_tot_len / METERS_PER_MILE))


# "DBG:********"; from pdb import set_trace as bp; bp()

# dirs = json.loads(directions_result)[0]
#
# print('Results are: {}'.format(pprint.pprint(dirs, indent=4)))
#
# legs = directions_result['legs']
# print('\n\n**************\nResults are: {}'.format(pprint.pprint(legs, indent=4)))
