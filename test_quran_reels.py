import unittest
from quran_reels import canonical_tokens, normalize_ar, align_words, english_parts

class QuranTests(unittest.TestCase):
    def test_ornament_attached_without_losing_text(self):
        text='بِذِكْرِ ٱللَّهِ ۗ أَلَا'
        self.assertEqual(canonical_tokens(text),['بِذِكْرِ','ٱللَّهِ ۗ','أَلَا'])
        self.assertEqual(' '.join(canonical_tokens(text)),text)
    def test_normalization(self):
        self.assertEqual(normalize_ar('ءَامَنُوا۟'),normalize_ar('آمنوا'))
        self.assertEqual(normalize_ar('وَتَطْمَئِنُّ'),normalize_ar('وتطمئن'))
    def test_missing_phrase_not_fabricated(self):
        words=['الله','ألا','بذكر','الله']
        heard=[{'w':'الله','start':0.,'end':1.}]
        timings,report=align_words(words,heard,4.)
        self.assertEqual(report['match_ratio'],.25)
        self.assertEqual(sum(t is None for t in timings),3)
    def test_exact_match(self):
        timings,r=align_words(['ٱللَّهِ'],[{'w':'الله','start':1.,'end':2.}],3.)
        self.assertEqual(timings,[(1.,2.)]);self.assertFalse(r['unmatched'])
    def test_semantic_clause_boundary(self):
        a={'words':['one','two ۗ','three'],'english':'First sentence. Second sentence.'}
        self.assertEqual(english_parts(a),[(0,2,'First sentence.'),(2,3,'Second sentence.')])
    def test_no_arbitrary_english_split(self):
        a={'words':['one','two','three'],'english':'First sentence. Second sentence.'}
        self.assertEqual(english_parts(a),[(0,3,a['english'])])

if __name__=='__main__': unittest.main()
