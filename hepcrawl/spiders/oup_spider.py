# -*- coding: utf-8 -*-
#
# This file is part of hepcrawl.
# Copyright (C) 2015, 2016 CERN.
#
# hepcrawl is a free software; you can redistribute it and/or modify it
# under the terms of the Revised BSD License; see LICENSE file for
# more details.

"""Spider for Oxford University Press."""

from __future__ import absolute_import, print_function

import os
#import urlparse

from scrapy import Request
from scrapy.spiders import XMLFeedSpider
import ftputil

from zipfile import ZipFile

from inspire_schemas.api import validate as validate_schema

from ..extractors.jats import Jats
from ..items import HEPRecord
from ..loaders import HEPLoader
from ..utils import (
    ftp_list_files,
    ftp_connection_info,
    get_license
)

from ..settings import OXFORD_DOWNLOAD_DIR, OXFORD_UNPACK_FOLDER

def unzip_files(filename, target_folder, type=".xml"):
    """Unzip files (XML only) into target folder."""
    z = ZipFile(filename)
    xml_files = []
    for filename in z.namelist():
        if filename.endswith(type):
            absolute_path = os.path.join(target_folder, filename)
            if not os.path.exists(absolute_path):
                z.extract(filename, target_folder)
            xml_files.append(absolute_path)
    return xml_files


def ftp_list_folders(server_folder, server, user, password):
    """List files from given FTP's server folder to target folder."""
    with ftputil.FTPHost(server, user, password) as host:
        folders = host.listdir(host.curdir + '/' + server_folder)
        all_folders = []
        for folder in folders:
            if not folder.startswith('.'):
                all_folders.append(folder)
    return all_folders


def generate_download_name():
    from time import localtime, strftime
    return strftime('%Y-%m-%d_%H:%M:%S', localtime())


def get_arxiv(node):
    arxivs_raw = node.xpath("//article-id[@pub-id-type='arxiv']/text()")
    for arxiv in arxivs_raw:
            ar = arxiv.extract()
            if ar:
                return ar 
    return None


class OxfordUniversityPressSpider(Jats, XMLFeedSpider):
    """Oxford University Press SCOAP3 crawler.

    This spider connects to a given FTP hosts and downloads zip files with
    XML files for extraction into HEP records.

    This means that it generates the URLs for Scrapy to crawl in a special way:

    1. First it connects to a FTP host and lists all the new ZIP files found
       on the remote server and downloads them to a designated local folder,
       using `start_requests()`.

    2. Then the ZIP file is unpacked and it lists all the XML files found
       inside, via `handle_package()`. Note the callback from `start_requests()`

    3. Finally, now each XML file is parsed via `parse_node()`.

    To run a crawl, you need to pass FTP connection information via
    `ftp_host` and `ftp_netrc`:``

    .. code-block:: console

        scrapy crawl OUP -a 'ftp_host=ftp.example.com' -a 'ftp_netrc=/path/to/netrc'


    Happy crawling!
    """

    name = 'OUP'
    custom_settings = {}
    start_urls = []
    iterator = 'html'  # this fixes a problem with parsing the record
    itertag = 'article'

    allowed_article_types = [
        'research-article',
        'corrected-article',
        'original-article',
        'introduction',
        'letter',
        'correction',
        'addendum',
        'review-article',
        'rapid-communications'
    ]

    article_type_mapping = {
        'research-article': 'article',
        'corrected-article': 'article',
        'original-article': 'article',
        'correction': 'corrigendum',
        'addendum': 'addendum',
        'introduction': 'other',
        'letter': 'other',
        'review-article': 'other',
        'rapid-communications': 'other'
    }
    default_article_type = 'unknown'

    def __init__(self, package_path=None, ftp_folder="hooks", ftp_host=None, ftp_netrc=None, *args, **kwargs):
        """Construct WSP spider."""
        super(OxfordUniversityPressSpider, self).__init__(*args, **kwargs)
        self.ftp_folder = ftp_folder
        self.ftp_host = ftp_host
        self.ftp_netrc = ftp_netrc
        self.target_folder = OXFORD_DOWNLOAD_DIR
        self.package_path = package_path
        if not os.path.exists(self.target_folder):
            os.makedirs(self.target_folder)

    def start_requests(self):
        """List selected folder on remote FTP and yield new zip files."""
        if self.package_path:
            yield Request(self.package_path, callback=self.handle_package_file)
        else:
            ftp_host, ftp_params = ftp_connection_info(self.ftp_host, self.ftp_netrc)
            for folder in ftp_list_folders(
                self.ftp_folder,
                server=ftp_host,
                user=ftp_params['ftp_user'],
                password=ftp_params['ftp_password']
            ):
                new_download_name = generate_download_name()
                new_files, dummy = ftp_list_files(
                    os.path.join(self.ftp_folder,folder),
                    self.target_folder,
                    server=ftp_host,
                    user=ftp_params['ftp_user'],
                    password=ftp_params['ftp_password']
                )
                for remote_file in new_files:
                    # Cast to byte-string for scrapy compatibility
                    remote_file = str(remote_file)
                    if '.zip' in remote_file:
                        ftp_params["ftp_local_filename"] = os.path.join(
                            self.target_folder,
                            "_".join([new_download_name,os.path.basename(remote_file)])
                        )
                        remote_url = "ftp://{0}/{1}".format(ftp_host, remote_file)
                        yield Request(
                            str(remote_url),
                            meta=ftp_params,
                            callback=self.handle_package_ftp
                        )

    def handle_package_ftp(self, response):
        """Handle a zip package and yield every XML found."""
        self.log("Visited %s" % response.url)
        zip_filepath = response.body
        zip_target_folder = zip_filepath
        while True:
            zip_target_folder, dummy = os.path.splitext(zip_target_folder)
            if dummy == '':
                break

        if ".pdf" in zip_filepath:
            zip_target_folder = os.path.join(zip_target_folder,"pdf")
            unzip_files(zip_filepath, zip_target_folder, ".pdf")
        if zip_target_folder.endswith("_archival"):
            zip_target_folder = zip_target_folder[0:zip_target_folder.find("_archival")]
            zip_target_folder = os.path.join(zip_target_folder,"archival")
            unzip_files(zip_filepath, zip_target_folder, ".pdf")
        if ".xml" in zip_filepath:
            xml_files = unzip_files(zip_filepath, zip_target_folder)
            for xml_file in xml_files:
                dir_path = os.path.dirname(xml_file)
                filename = os.path.basename(xml_file).split('.')[0]
                pdf_url = os.path.join(dir_path,"pdf","%s.%s" % (filename,'pdf'))
                pdfa_url = os.path.join(dir_path,"archival","%s.%s" % (filename,'pdf'))
                yield Request(
                   "file://{0}".format(xml_file),
                   meta={"package_path": zip_filepath,
                         "xml_url": xml_file,
                         "pdf_url": pdf_url,
                         "pdfa_url": pdfa_url}
                )

    def parse_node(self, response, node):
        """Parse a OUP XML file into a HEP record."""
        node.remove_namespaces()
        article_type = node.xpath('@article-type').extract().lower()
        self.log("Got article_type {0}".format(article_type))
        if article_type is None or article_type[0] not in self.allowed_article_types:
            # Filter out non-interesting article types
            return None

        record = HEPLoader(item=HEPRecord(), selector=node, response=response)
        if article_type in ['correction',
                            'addendum']:
            record.add_xpath('related_article_doi', "//related-article[@ext-link-type='doi']/@href")
        record.add_xpath('dois', "//article-id[@pub-id-type='doi']/text()")
        record.add_value('report_numbers', [{
            'source': 'arXiv',
            'value': get_arxiv(node)
        }])
        record.add_xpath('page_nr', "//counts/page-count/@count")

        record.add_xpath('abstract', '//abstract[1]')
        record.add_xpath('title', '//article-title/text()')
        record.add_xpath('subtitle', '//subtitle/text()')

        record.add_value('authors', self._get_authors(node))
        record.add_xpath('collaborations', "//contrib/collab/text()")

        free_keywords, classification_numbers = self._get_keywords(node)
        record.add_value('free_keywords', free_keywords)
        record.add_value('classification_numbers', classification_numbers)

        record.add_value('date_published', self._get_published_date(node))

        # TODO: Special journal title handling
        # journal, volume = fix_journal_name(journal, self.journal_mappings)
        # volume += get_value_in_tag(self.document, 'volume')
        journal_title = '//abbrev-journal-title/text()|//journal-title/text()'
        record.add_xpath('journal_title', journal_title)
        record.add_xpath('journal_issue', '//issue/text()')
        record.add_xpath('journal_volume', '//volume/text()')
        record.add_xpath('journal_artid', '//elocation-id/text()')

        record.add_xpath('journal_fpage', '//fpage/text()')
        record.add_xpath('journal_lpage', '//lpage/text()')

        published_date = self._get_published_date(node)
        record.add_value('journal_year', int(published_date[:4]))
        record.add_value('date_published', published_date)

        record.add_xpath('copyright_holder', '//copyright-holder/text()')
        record.add_xpath('copyright_year', '//copyright-year/text()')
        record.add_xpath('copyright_statement', '//copyright-statement/text()')
        record.add_value('copyright_material', 'Article')

        license = get_license(
            license_url=node.xpath('//license/license-p/ext-link/text()').extract_first()
        )
        record.add_value('license', license)

        record.add_value('collections', ['Progress of Theoretical and Experimental Physics'])

        record.add_value('original_doctype', article_type)
        record.add_value('doctype', self.article_type_mapping.get(article_type, self.default_article_type))

        #local fiels paths
        local_files = []
        if 'xml_url' in response.meta:
            local_files.append({'filetype':'xml', 'path':response.meta['xml_url']})
        if 'pdf_url' in response.meta:
            local_files.append({'filetype':'pdf', 'path':response.meta['pdf_url']})
        if 'pdfa_url' in response.meta:
            local_files.append({'filetype':'pdf/a', 'path':response.meta['pdfa_url']})
        record.add_value('local_files', local_files)

        # DIRTY HACK to pass schema validation for prublisher name
        self.name = "Oxford University Press"

        parsed_record = dict(record.load_item())
        print(parsed_record)
        return parsed_record

    # def _get_collections(self, node, article_type, current_journal_title):
    #     """Return this articles' collection."""
    #     conference = node.xpath('.//conference').extract()
    #     if conference or current_journal_title == "International Journal of Modern Physics: Conference Series":
    #         return ['HEP', 'ConferencePaper']
    #     elif article_type == "review-article":
    #         return ['HEP', 'Review']
    #     else:
    #         return ['HEP', 'Published']
