import datetime
import logging
import re

from ..items import HEPRecord
from ..loaders import HEPLoader
from ..utils import get_license

logger = logging.getLogger(__name__)


class S3ElsevierParser(object):
    article_type_mapping = {
        'article': 'article',
        'sco': 'article',
        'fla': 'article',
        'abs': 'article',
        'rev': 'article',
        'add': 'addendum',
        'edb': 'editorial',
        'edi': 'editorial',
        'err': 'erratum',
        'ret': 'retraction',
        'rem': 'retraction',
        'adv': 'other',
        'ann': 'other',
        'brv': 'other',
        'cal': 'other',
        'chp': 'other',
        'cnf': 'other',
        'con': 'other',
        'cop': 'other',
        'cor': 'other',
        'crp': 'other',
        'dis': 'other',
        'dup': 'other',
        'exm': 'other',
        'ind': 'other',
        'lit': 'other',
        'mis': 'other',
        'nws': 'other',
        'ocn': 'other',
        'pgl': 'other',
        'pnt': 'other',
        'prp': 'other',
        'prv': 'other',
        'pub': 'other',
        'req': 'other',
        'ssu': 'other'
    }

    def parse_node(self, meta, node):
        """Parse a OUP XML file into a HEP record."""
        node.remove_namespaces()
        record = HEPLoader(item=HEPRecord(), selector=node)

        article_type = node.xpath('./@docsubtype').extract()
        article_type = map(lambda x: self.article_type_mapping.get(x, 'other'), article_type)
        record.add_value('journal_doctype', article_type)

        dois = node.xpath('./item-info/doi/text()').extract()
        doi = dois[0]
        record.add_value('dois', dois)

        if article_type in ['correction', 'addendum']:
            logger.info('Adding related_article_doi for article %s.' % dois)
            record.add_xpath('related_article_doi', "//related-article[@ext-link-type='doi']/@href")

        record.add_xpath('abstract', './*[self::head | self::simple-head]/abstract[1]/abstract-sec')
        record.add_xpath('title', './*[self::head | self::simple-head]/title/text()')
        record.add_xpath('subtitle', './*[self::head | self::simple-head]/subtitle/text()')

        record.add_value('authors', self.get_authors(node, dois))
        record.add_xpath('collaborations', "./*[self::head | self::simple-head]/author-group/collaboration/text/text()")

        record.add_value('journal_title', meta['articles'][doi]['journal'])
        record.add_value('journal_volume', meta['volume'])
        record.add_xpath('journal_artid', '//item-info/aid/text()')

        first_page = meta['articles'][doi].get('first-page')
        last_page = meta['articles'][doi].get('last-page')
        record.add_value('journal_fpage', first_page)
        record.add_value('journal_lpage', last_page)

        if first_page is not None and last_page is not None:
            try:
                page_nr = int(last_page) - int(first_page) + 1
                record.add_value('page_nr', page_nr)
            except ValueError as e:
                logger.error('Failed to parse last_page or first_page for article %s: %s' % (dois, e))

        published_date = datetime.datetime.strptime(meta['articles'][doi]['publication-date'], "%Y-%m-%dT%H:%M:%S")
        record.add_value('journal_year', published_date.year)
        record.add_value('date_published', published_date.strftime("%Y-%m-%d"))

        record.add_xpath('copyright_holder', './item-info/copyright/text()')
        record.add_xpath('copyright_year', './item-info/copyright/@year')
        record.add_xpath('copyright_statement', './item-info/copyright/text()')

        license = get_license(
            license_url='http://creativecommons.org/licenses/by/3.0/'
        )
        record.add_value('license', license)

        record.add_value('collections', [meta['articles'][doi]['journal']])

        # local file paths
        local_files = []
        for filetype in meta['articles'][doi]['files']:
            local_files.append({'filetype': filetype, 'path': meta['articles'][doi]['files'][filetype]})
        record.add_value('local_files', local_files)

        return dict(record.load_item())

    def get_authors(self, node, dois):
        """Get the authors."""
        authors = []

        for author_group in node.xpath("//author-group"):
            for author in author_group.xpath("./author"):
                surname = author.xpath("./surname/text()")
                given_names = author.xpath("./given-name/text()")
                affiliations = self._get_affiliations(author_group, author, dois)
                orcid = self._get_orcid(author)
                emails = author.xpath("./e-address/text()")

                auth_dict = {}

                if surname:
                    auth_dict['surname'] = surname.extract_first()
                if given_names:
                    auth_dict['given_names'] = given_names.extract_first()
                if orcid:
                    auth_dict['orcid'] = orcid
                if affiliations:
                    auth_dict['affiliations'] = [{"value": aff} for aff in affiliations]
                if emails:
                    auth_dict['email'] = emails.extract_first()

                authors.append(auth_dict)

        if not authors:
            logger.error('No authors found for article %s.' % dois)

        return authors

    @staticmethod
    def _get_orcid(author):
        """Return an authors ORCID number."""
        orcid_raw = author.xpath("./@orcid").extract_first()
        if orcid_raw:
            return "ORCID:{0}".format(orcid_raw)

    @staticmethod
    def _find_affiliations_by_id(author_group, ref_ids):
        """Return affiliations with given ids.

        Affiliations should be standardized later.
        """
        affiliations_by_id = []
        for aff_id in ref_ids:
            ce_affiliation = author_group.xpath("//affiliation[@id='" + aff_id + "']")
            if ce_affiliation.xpath(".//affiliation"):
                aff = ce_affiliation.xpath(".//*[self::organization or self::city or self::country or self::address-line]/text()")
                affiliations_by_id.append(", ".join(aff.extract()))
            elif ce_affiliation:
                aff = ce_affiliation.xpath("./textfn/text()").extract_first()
                aff = re.sub(r'^(\d+ ?)', "", aff)
                affiliations_by_id.append(aff)

        return affiliations_by_id

    def _get_affiliations(self, author_group, author, dois):
        """Return one author's affiliations.

        Will extract authors affiliation ids and call the
        function _find_affiliations_by_id().
        """

        ref_ids = author.xpath(".//@refid").extract()
        group_affs = author_group.xpath(".//affiliation[not(@*)]/textfn/text()")
        all_group_affs = author_group.xpath(".//affiliation/textfn/text()")

        # Don't take correspondence (cor1) or deceased (fn1):
        ref_ids = filter(lambda x: 'aff' in x, ref_ids)

        affiliations = []
        affiliations += self._find_affiliations_by_id(author_group, ref_ids)
        affiliations += group_affs.extract()

        # if we have no affiliations yet, we got a bad xml, without affiliation cross references.
        # in these cases it seems all group affiliation should be attached to all authors.
        if not affiliations:
            author_ids = author.xpath('./@author-id').extract()
            logger.error('Not found referenced affiliations (%s), adding all in the group for author '
                         'with id: %s for article %s' % (ref_ids, author_ids, dois))
            affiliations += all_group_affs.extract()

        return affiliations
