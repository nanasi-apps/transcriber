from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transcriber.merge import _split_text_chunks, merge_proportional
from transcriber.schema import DiarizationSegment


class MergeChunkingTests(unittest.TestCase):
    def test_long_unpunctuated_text_is_split_into_multiple_chunks(self) -> None:
        text = (
            "多分私もその認識で今回どうしてもうめちゃくちゃ大前提の話から大前提の話"
            "ひっくり返すことになっちゃうんだよななっちゃうんだけどどうして今晩環境を"
            "変える必要があったのかが分かってないっていうのがあるんだけどそこも含めですよ"
            "多分きっとうんそこも含めおそらくなんだろう本番の環境は絶対いじるなよだったり"
            "そこの部分の徹底周知まあ当然なんですけど絶対いじるなよっていうのを徹底周知"
            "だったりそのままそうですねまあ言いたいことはそらさんが言っていた通りなので"
            "西塚さんの認識がどうなっているのかなという部分でペースがいまいち私はよく"
            "理解できてなくてそこが一番大切になってくると思ってたのでそのそうですね"
            "私の中では何かイメージつかめたんですけどそらさん的にどう"
        )

        chunks = _split_text_chunks(text)

        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(chunk.strip() for chunk in chunks))

    def test_merge_proportional_splits_single_long_turn(self) -> None:
        text = (
            "多分私もその認識で今回どうしてもうめちゃくちゃ大前提の話から大前提の話"
            "ひっくり返すことになっちゃうんだよななっちゃうんだけどどうして今晩環境を"
            "変える必要があったのかが分かってないっていうのがあるんだけどそこも含めですよ"
            "多分きっとうんそこも含めおそらくなんだろう本番の環境は絶対いじるなよだったり"
            "そこの部分の徹底周知まあ当然なんですけど絶対いじるなよっていうのを徹底周知"
            "だったりそのままそうですねまあ言いたいことはそらさんが言っていた通りなので"
            "西塚さんの認識がどうなっているのかなという部分でペースがいまいち私はよく"
            "理解できてなくてそこが一番大切になってくると思ってたのでそのそうですね"
            "私の中では何かイメージつかめたんですけどそらさん的にどう"
        )
        diarization = [DiarizationSegment(speaker_id="speaker_02", start=569.0, end=625.0)]

        utterances = merge_proportional(text, diarization)

        self.assertGreater(len(utterances), 1)
        self.assertEqual("".join(utterance.text for utterance in utterances), text)
        self.assertEqual(utterances[0].start, 569.0)
        self.assertEqual(utterances[-1].end, 625.0)


if __name__ == "__main__":
    unittest.main()
