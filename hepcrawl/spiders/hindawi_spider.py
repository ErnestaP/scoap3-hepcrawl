# -*- coding: utf-8 -*-
#
# This file is part of hepcrawl.
# Copyright (C) 2016 CERN.
#
# hepcrawl is a free software; you can redistribute it and/or modify it
# under the terms of the Revised BSD License; see LICENSE file for
# more details.

"""Spider for Hindawi."""

from __future__ import absolute_import, print_function

import logging

from scrapy import Request
from scrapy.spiders import XMLFeedSpider

from hepcrawl.extractors.hindawi_parser import HindawiParser


class HindawiSpider(XMLFeedSpider):

    """Hindawi crawler

    OAI interface: http://www.hindawi.com/oai-pmh/
    Example:
    http://www.hindawi.com/oai-pmh/oai.aspx?verb=listrecords&set=HINDAWI.AA&metadataprefix=marc21&from=2015-01-01

    Sets to use:
    HINDAWI.AA (Advances in Astronomy)
    HINDAWI.AHEP (Advances in High Energy Physics)
    HINDAWI.AMP (Advances in Mathematical Physics)
    HINDAWI.JAS (Journal of Astrophysics)
    HINDAWI.JCMP (Journal of Computational Methods in Physics)
    HINDAWI.JGRAV (Journal of Gravity)

    Scrapes Hindawi metadata XML files one at a time.
    The actual files should be retrieved from Hindawi via its OAI interface.
    The file can contain multiple records.

    1. The spider will parse the local MARC21XML format file for record data

    2. Finally a HEPRecord will be created.


    Example usage:
    .. code-block:: console

        scrapy crawl hindawi -a source_file=file://`pwd`/tests/responses/hindawi/test_1.xml

    Happy crawling!
    """

    name = 'hindawi'
    start_urls = []
    iterator = 'xml'
    itertag = 'marc:record'

    namespaces = [
        ("OAI-PMH", "http://www.openarchives.org/OAI/2.0/"),
        ("marc", "http://www.loc.gov/MARC21/slim"),
        ("mml", "http://www.w3.org/1998/Math/MathML"),
    ]

    def __init__(self, source_file=None, *args, **kwargs):
        """Construct Hindawi spider."""
        super(HindawiSpider, self).__init__(*args, **kwargs)
        self.source_file = source_file

    def start_requests(self):
        """Default starting point for scraping shall be the local XML file."""
        self.log('Harvest started.', logging.INFO)
        headers = {
            'User-Agent': 'curl/7.64.1'
        }
        yield Request(self.source_file, headers=headers)

    def parse_node(self, response, node):
        self.log('Parsing node...', logging.INFO)
        parser = HindawiParser()
        return parser.parse_node(response, node)
