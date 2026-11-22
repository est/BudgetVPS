import unittest

from scraper.cf import looks_like_challenge, looks_like_challenge_body

# 真实的 CF 验证页：标题是 Just a moment，整页只有几 KB
CHALLENGE_PAGE = """<!DOCTYPE html><html><head><title>Just a moment...</title>
<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script>
<script>window._cf_chl_opt = {cvId: '3'};</script>
</head><body>Verifying you are human</body></html>"""

# Hosteons 的真实商品页：标题是 Shopping Cart，很大，而且 body 里**也有**
# challenge-platform（CF 注入到每个页面的脚本）
HOSTEONS_PAGE = (
    "<!doctype html><html><head><title>Shopping Cart - hostEONS.com</title></head><body>"
    '<div class="product-info"><p class="product-title">RYZEN 7 GB</p></div>'
    + "x" * 83000
    + '<script src="/cdn-cgi/challenge-platform/h/b/scripts/main.js"></script>'
    + '</body></html>'
)

# 正文里出现 "Attention Required" 的产品页
PRODUCT_TEXT_PAGE = """
<div class="product-info">
    <p class="product-title">Attention Required: Email Hosting</p>
    <p>1 GB RAM<br />20 GB SSD<br />Please read this carefully.</p>
</div>
"""


class ChallengeDetectionTest(unittest.TestCase):
    def test_challenge_page_detected_on_200(self):
        self.assertTrue(looks_like_challenge_body(CHALLENGE_PAGE))

    def test_normal_page_with_cf_scripts_is_not_a_challenge(self):
        # HTTP 200 的正常商品页里本来就有 challenge-platform，不能被误判
        self.assertFalse(looks_like_challenge_body(HOSTEONS_PAGE))
        self.assertIn("challenge-platform", HOSTEONS_PAGE)

    def test_product_text_is_not_a_challenge(self):
        self.assertFalse(looks_like_challenge_body(PRODUCT_TEXT_PAGE))

    def test_status_403_path_still_uses_loose_markers(self):
        self.assertTrue(looks_like_challenge(CHALLENGE_PAGE))
        self.assertFalse(looks_like_challenge('<div class="product-info">hi</div>'))
        # Hosteons 的 CF 脚本在第 83089 字节，不在前 6000 字节里
        self.assertFalse(looks_like_challenge(HOSTEONS_PAGE))


if __name__ == "__main__":
    unittest.main()
