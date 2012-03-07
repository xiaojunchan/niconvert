#!/usr/bin/python
# -*- coding: utf-8 -*-

# ----------------------------------------------------------------------------
#     Name: niconvert
#     Desc: 弹幕字幕下载和转换工具
#    Usage: ./niconvert -h
# ----------------------------------------------------------------------------

import re
import json
import logging
import urllib2
import gzip
import zlib
from StringIO import StringIO
from argparse import ArgumentParser
from xml.dom.minidom import parseString

ASS_HEADER_TPL = """[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: %(video_width)s
PlayResY: %(video_height)s

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, BackColour, OutlineColour, Bold, Italic, Alignment, BorderStyle, Outline, Shadow, MarginL, MarginR, MarginV
Style: NicoDefault,%(font_name)s,%(font_size)s,&H00FFFFFF,&H00000000,&H00000000,0,0,2,1,1,0,20,20,20

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:10.0.2) Gecko/20100101 Firefox/10.0.2"

def get_logger(logger_name):
    format_string = '%(asctime)s %(levelname)5s %(message)s'
    level = logging.WARNING
    logging.basicConfig(format=format_string, level=level)
    logger = logging.getLogger(logger_name)
    return logger

logger = get_logger('niconvert')

def fetch_url(url):
    opener = urllib2.build_opener()
    opener.addheaders = [
        ('User-Agent', USER_AGENT),
        ('Accept-Encoding', 'gzip')
    ]
    resp = opener.open(url)
    content = resp.read()
    content_encoding = resp.headers.get('content-encoding', None)
    if content_encoding == 'gzip':
        content = gzip.GzipFile(fileobj=StringIO(content), mode='rb').read()
    elif content_encoding == 'deflate':
        content = zlib.decompressobj(-zlib.MAX_WBITS).decompress(content)
    return content

class NicoSubtitle:

    (SCROLL, TOP, BOTTOM, NOT_SUPPORT) = range(4)
    FLASH_FONT_SIZE = 25 # office flash player font size

    def __init__(self):
        self.index = None
        self.start_seconds = None
        self.font_size = None
        self.font_color = None
        self.style = None
        self.text = None

    def __unicode__(self):
        return u'#%05d, %d, %d, %s, %s, %s' % (
                self.index, self.style,
                self.font_size, self.font_color,
                self.start_seconds, self.text)

    def __str__(self):
        return self.__unicode__().encode('utf-8')

    @staticmethod
    def to_style(attr):
        if attr == 1:
            style = NicoSubtitle.SCROLL
        elif attr == 4:
            style = NicoSubtitle.BOTTOM
        elif attr == 5:
            style = NicoSubtitle.TOP
        else:
            style = NicoSubtitle.NOT_SUPPORT
        return style

    @staticmethod
    def to_gbr(integer):
        rgb = "%06s" % hex(integer).upper()[2:]
        gbr = rgb[2:] + rgb[:2] # ass use gbr
        return gbr

class AssSubtitle:

    def __init__(self, nico_subtitle,
                 video_width, video_height,
                 base_font_size, line_count):

        self.nico_subtitle = nico_subtitle
        self.video_width = video_width
        self.video_height = video_height
        self.base_font_size = base_font_size
        self.line_count = line_count

        self.text_length = self.init_text_length()
        self.start = self.init_start()
        self.end = self.init_end()
        self.font_size = self.init_font_size()
        (self.x1, self.y1,
         self.x2, self.y2) = self.init_position();
        self.styled_text = self.init_styled_text()

    @staticmethod
    def to_hms(seconds):
        if seconds < 0:
            return '00:00:00.000'

        i, d = divmod(seconds, 1)
        m, s = divmod(i, 60)
        h, m = divmod(m, 60)
        return "%02d:%02d:%02d.%03d" % (h, m, s, d * 1000)

    def init_text_length(self):
        return float(len(self.nico_subtitle.text))

    def init_start(self):
        return AssSubtitle.to_hms(self.nico_subtitle.start_seconds)

    def init_end(self):
        if self.nico_subtitle.style == NicoSubtitle.TOP:
            return AssSubtitle.to_hms(self.nico_subtitle.start_seconds + 4)

        if self.text_length < 5:
            end_seconds = self.nico_subtitle.start_seconds + 4 + (self.text_length / 1.5)
        elif self.text_length < 12:
            end_seconds = self.nico_subtitle.start_seconds + 4 + (self.text_length / 2)
        else:
            end_seconds = self.nico_subtitle.start_seconds + 10
        return AssSubtitle.to_hms(end_seconds)

    def init_font_size(self):
        return self.nico_subtitle.font_size - NicoSubtitle.FLASH_FONT_SIZE + self.base_font_size

    def init_position(self):
        if self.nico_subtitle.style == NicoSubtitle.SCROLL:
            x1 = self.video_width + (self.base_font_size * self.text_length) / 2
            x2 = -(self.base_font_size * self.text_length) / 2
            y = (self.nico_subtitle.index % (self.line_count + 1)) * self.base_font_size
            return (x1, y, x2 , y)
        elif self.nico_subtitle.style == NicoSubtitle.BOTTOM:
            x = self.video_width / 2
            y = self.video_height - (self.base_font_size * 2)
            return (x, y, x, y)
        else: # TOP
            x = self.video_width / 2
            y = 1
            return (x, y, x, y)

    def init_styled_text(self, ):
        if self.nico_subtitle.font_color == 'FFFFFF':
            color_markup = ""
        else:
            color_markup = "\\c&H%s" % self.nico_subtitle.font_color
        if self.font_size == self.base_font_size:
            font_size_markup = ""
        else:
            font_size_markup = "\\fs%d" % self.font_size
        if self.nico_subtitle.style == NicoSubtitle.SCROLL:
            style_markup = "\\move(%d, %d, %d, %d)" % (self.x1, self.y1, self.x2, self.y2)
        else:
            style_markup = "\\a6\\pos(%d, %d)" % (self.x1, self.y1)
        markup = "".join([style_markup, color_markup, font_size_markup])
        return "{%s}%s" % (markup, self.nico_subtitle.text)

    @property
    def ass_line(self):
        return "Dialogue: 3,%(start)s,%(end)s,NicoDefault,,0000,0000,0000,,%(styled_text)s" % dict(
                start=self.start,
                end=self.end,
                styled_text=self.styled_text)

class Downloader:

    TITLE_RE = re.compile('<title>(.*)</title>')
    COMMENT_URL_RE = re.compile('flashvars="([^"]+)"')

    def __init__(self, url):
        self.url = url
        self.html = self.get_html()
        self.title = self.get_title()
        self.comment_url = self.get_comment_url()
        self.comment_text = self.get_comment_text()

    def get_html(self):
        raise NotImplementedError

    def get_title(self):
        title = Downloader.TITLE_RE.findall(self.html)[0].split(' - ')[0]
        logger.info(u'视频标题: %s', title)
        return title

    def get_comment_url(self):
        raise NotImplementedError

    def get_comment_text(self):
        return fetch_url(self.comment_url)

class BilibiliDownloader(Downloader):

    def __init__(self, url):
        Downloader.__init__(self, url)

    def get_html(self):
        return fetch_url(self.url).decode('UTF-8')

    def get_comment_url(self):
        flashvars = Downloader.COMMENT_URL_RE.findall(self.html)[0].split('=')[1]
        comment_url = 'http://comment.bilibili.tv/dm,' + flashvars
        logger.info(u'评论地址: %s', comment_url)
        return comment_url

class AcfunDownloader(Downloader):

    def __init__(self, url):
        Downloader.__init__(self, url)

    def get_html(self):
        return fetch_url(self.url).decode('GBK')

    def get_comment_url(self):
        flashvars = Downloader.COMMENT_URL_RE.findall(self.html)[0].split('id=')[-1]
        comment_url = 'http://comment.acfun.tv/%s.json' % flashvars
        logger.info(u'评论地址: %s', comment_url)
        return comment_url

class Website:

    def __init__(self, url):
        self.url = url
        self.downloader = self.create_downloader()
        self.nico_subtitles = self.create_nico_subtitles()

    def create_downloader(self):
        raise NotImplementedError

    def create_nico_subtitles(self):
        raise NotImplementedError

    def ass_subtitles_text(self, font_name, font_size, resolution, line_count):

        video_width, video_height = map(int, resolution.split(':'))
        if font_size == 0:
            # 1280 宽度用 50 像素字体看起来不错，不同宽度按此比例缩放
            font_size = video_width * 50 / 1280

        ass_subtitles = []
        for nico_subtitle in self.nico_subtitles:
            ass_subtitle = AssSubtitle(nico_subtitle,
                                       video_width, video_height,
                                       font_size, line_count)
            ass_subtitles.append(ass_subtitle)

        ass_lines = []
        for ass_subtitle in ass_subtitles:
            ass_lines.append(ass_subtitle.ass_line)

        ass_header = ASS_HEADER_TPL % dict(video_width=video_width,
                                           video_height=video_height,
                                           font_name=font_name,
                                           font_size=font_size)
        text = ass_header + "\n".join(ass_lines)
        return text

class Bilibili(Website):

    def __init__(self, url):
        Website.__init__(self, url)

    def create_downloader(self):
        return BilibiliDownloader(self.url)

    def create_nico_subtitles(self):

        nico_subtitles = []
        dom = parseString(self.downloader.comment_text)
        nico_subtitle_xml_nodes = dom.getElementsByTagName('d')
        for node in nico_subtitle_xml_nodes:
            attributes = node.attributes.get('p').value.split(',')

            nico_subtitle = NicoSubtitle()
            nico_subtitle.start_seconds = float(attributes[0])
            nico_subtitle.style = NicoSubtitle.to_style(int(attributes[1]))
            nico_subtitle.font_size = int(attributes[2])
            nico_subtitle.font_color = NicoSubtitle.to_gbr(int(attributes[3]))
            nico_subtitle.text = node.childNodes[0].data

            if nico_subtitle.style != NicoSubtitle.NOT_SUPPORT:
                nico_subtitles.append(nico_subtitle)
        nico_subtitles.sort(key=lambda x: x.start_seconds)

        for i, nico_subtitle in enumerate(nico_subtitles):
            nico_subtitle.index = i

        logger.info(u'字幕数量: (%d/%d)', len(nico_subtitles), len(nico_subtitle_xml_nodes))
        return nico_subtitles

class Acfun(Website):

    def __init__(self, url):
        Website.__init__(self, url)

    def create_downloader(self):
        return AcfunDownloader(self.url)

    def create_nico_subtitles(self):

        nico_subtitles = []
        nico_subtitle_json_list = json.loads(self.downloader.comment_text)
        for element in nico_subtitle_json_list:
            attributes = element['c'].split(',')

            nico_subtitle = NicoSubtitle()
            nico_subtitle.start_seconds = float(attributes[0])
            nico_subtitle.font_color = NicoSubtitle.to_gbr(int(attributes[1]))
            nico_subtitle.style = NicoSubtitle.to_style(int(attributes[2]))
            nico_subtitle.font_size = int(attributes[3])
            nico_subtitle.text = element['m']

            if nico_subtitle.style != NicoSubtitle.NOT_SUPPORT:
                nico_subtitles.append(nico_subtitle)
        nico_subtitles.sort(key=lambda x: x.start_seconds)

        for i, nico_subtitle in enumerate(nico_subtitles):
            nico_subtitle.index = i

        logger.info(u'字幕数量: (%d/%d)', len(nico_subtitles), len(nico_subtitle_json_list))
        return nico_subtitles

def get_commandline_arguments():
    argument_parser = ArgumentParser(description='弹幕字幕下载和转换工具')
    argument_parser.add_argument('url', help='弹幕视频网页地址',
                                 metavar='url', type=str)
    argument_parser.add_argument('-o', '--output', help='保存文件名，默认为网页标题',
                                 metavar='output', type=str, default=None)
    argument_parser.add_argument('-r', '--resolution', help='视频分辨率，格式如「1280:768」',
                                 metavar='resolution', type=str, default="1280:768")
    argument_parser.add_argument('-f', '--font_name', help='使用字体名称',
                                 metavar='font_name', type=str, default='WenQuanYi Micro Hei')
    argument_parser.add_argument('-s', '--font_size', help='默认字体大小',
                                 metavar='font_size', type=int, default=0)
    argument_parser.add_argument('-l', '--line_count', help='同屏弹幕行数',
                                 metavar='line_count', type=int, default=5)
    argument_parser.add_argument('-d', '--debug', help='输出调试日志',
                                 action='store_true')
    return argument_parser

def create_website(url):
    if url.find('bilibili.tv') != -1:
        return Bilibili(url)
    elif url.find('acfun.tv') != -1:
        return Acfun(url)
    else:
        return None

def main():
    args = get_commandline_arguments().parse_args().__dict__

    debug = args.pop('debug')
    if debug:
        logger.level = logging.DEBUG

    url = args.pop('url')
    website = create_website(url)
    if website is None:
        print '错误: 不支持的网站'
        exit(1)

    output = args.pop('output')
    if output is None:
        output = website.downloader.title + '.ass'

    text = website.ass_subtitles_text(**args)

    with open(output, 'w') as outfile:
        outfile.write(text.encode("UTF-8"))

if __name__ == '__main__':
    main()