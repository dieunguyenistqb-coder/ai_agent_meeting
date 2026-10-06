import unittest
from src.source_grounding import transcript_turns, citation_matches


class SourceTurnTests(unittest.TestCase):
    def setUp(self):
        self.text = ('Ngày họp: 10-10-2026\n\nNam (Backend):\n'
            'Đã xong API. Hôm nay em làm logging. Hiện tại không có blocker.\n\n'
            'Mai (Frontend):\nEm đang chờ API.\n\nNam (Backend):\nEm sẽ gửi sau.')
        self.turns=transcript_turns(self.text)

    def test_sentence_and_last_sentence(self):
        for excerpt in ('Nam (Backend): Hôm nay em làm logging.',
                        'Nam (Backend): Hiện tại không có blocker.',
                        'Nam (Backend): Đã xong API. Hôm nay em làm logging. Hiện tại không có blocker.'):
            self.assertTrue(citation_matches(excerpt,self.turns))

    def test_wrong_speaker_paraphrase_and_noncontiguous(self):
        for excerpt in ('Mai (Frontend): Hôm nay em làm logging.',
                        'Nam (Backend): Hôm nay em làm ghi log.',
                        'Nam (Backend): Đã xong API. Hiện tại không có blocker.',
                        'Nam (Backend): Hiện tại không có blocker. Em sẽ gửi sau.'):
            self.assertFalse(citation_matches(excerpt,self.turns))

    def test_whitespace_only(self):
        self.assertTrue(citation_matches(' Nam (Backend):\r\n Hôm nay   em làm logging.  ', self.turns))
        self.assertTrue(citation_matches('(PERSON2) làm API.',transcript_turns('(PERSON2) Đã họp. làm API.')))
        self.assertFalse(citation_matches('(PERSON1) làm API.',transcript_turns('(PERSON2) Đã họp. làm API.')))
