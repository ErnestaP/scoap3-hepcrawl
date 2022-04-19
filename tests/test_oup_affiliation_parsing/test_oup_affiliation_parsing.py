import pytest

from hepcrawl.extractors import oup_parser
import os

from scrapy.selector import Selector

files_for_testing = ['2022_oup_ptac032.xml',
                     '2021_oup_ptab168.xml', '2020_oup_ptaa186.xml']
correct_affiliations = {files_for_testing[0]:
                        ["Department of Physics, Graduate School of Science, Osaka University, , , Toyonaka, Osaka 560-0043, , , Japan"],
                        files_for_testing[1]: [
                            "Center for Gravitational Physics, Yukawa Institute for Theoretical Physics, Kyoto University, , , Kyoto 606-8502, , , Japan"],
                        files_for_testing[2]: [
                            "Institute of Science and Engineering, , Shimane University, , Matsue 690-8504, , Japan"]}


@pytest.fixture
def affiliations_from_records(shared_datadir):
    parsed_affiliations = {}
    for file in files_for_testing:
        parser = oup_parser.OUPParser()
        content=(shared_datadir / file).read_text()
        selector = Selector(text=content, type='xml')
        affiliations = parser._get_authors(selector)
        parsed_affiliations[os.path.basename(file)] = affiliations
    assert parsed_affiliations
    return parsed_affiliations


def test_country_in_OUP(affiliations_from_records):

    for file_name in files_for_testing:
        for affiliations_from_record in affiliations_from_records[file_name]:
            affiliations_values = []
            for affiliation_value_from_record in affiliations_from_record['affiliations']:
                affiliations_values.append(
                    affiliation_value_from_record['value'])
            # checking, are values the same
            assert len(affiliations_values) == len(correct_affiliations[file_name])
            assert (affiliations_values) == sorted(correct_affiliations[file_name])