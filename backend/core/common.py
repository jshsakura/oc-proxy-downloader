import math
import os
import random
import cloudscraper
import threading
import time

def convert_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return '0 B'
    size_name = ('B', 'KB', 'MB', 'GB', 'TB')
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return '%s %s' % (s, size_name[i])


def is_valid_link(url: str) -> bool:
    domains = [
        '1fichier.com/', 'afterupload.com/', 'cjoint.net/', 'desfichiers.com/',
        'megadl.fr/', 'mesfichiers.org/', 'piecejointe.net/', 'pjointe.com/',
        'tenvoi.com/', 'dl4free.com/', 'ouo.io/'
    ]
    return any([x in url.lower() for x in domains]) 