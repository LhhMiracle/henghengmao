"""
抖音商品详情页图片解析器
Douyin Product Image Parser - Extract all images from product detail page
"""

import re
import json
import httpx
import asyncio
from typing import List, Optional
from pydantic import BaseModel
from playwright.async_api import async_playwright

# 可选导入 undetected-chromedriver
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    HAS_UNDETECTED = True
except ImportError:
    HAS_UNDETECTED = False


class ProductImage(BaseModel):
    """商品图片模型"""
    url: str
    width: int = 0
    height: int = 0
    image_type: str = "main"  # main, detail, sku


class ProductInfo(BaseModel):
    """商品信息模型"""
    product_id: str
    title: str
    price: str = ""
    original_price: str = ""
    shop_name: str = ""
    sales: str = ""
    main_images: List[ProductImage] = []  # 主图
    detail_images: List[ProductImage] = []  # 详情图
    sku_images: List[ProductImage] = []  # SKU图片
    video_url: Optional[str] = None  # 商品视频


class DouyinProductParser:
    """抖音商品详情页解析器"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.douyin.com/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        self.client = httpx.AsyncClient(
            headers=self.headers,
            follow_redirects=True,
            timeout=30.0
        )

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()

    def extract_product_id(self, url: str) -> Optional[str]:
        """
        从抖音商品链接中提取商品ID
        支持格式:
        - https://www.douyin.com/goods/7123456789012345678
        - https://haohuo.douyin.com/goods/7123456789012345678
        - https://buyin.douyin.com/products/7123456789012345678
        - 分享链接短链
        """
        # 标准商品链接
        match = re.search(r'/goods/(\d+)', url)
        if match:
            return match.group(1)

        match = re.search(r'/products/(\d+)', url)
        if match:
            return match.group(1)

        # URL参数中的ID
        match = re.search(r'product_id=(\d+)', url)
        if match:
            return match.group(1)

        match = re.search(r'id=(\d+)', url)
        if match:
            return match.group(1)

        return None

    async def get_real_url(self, short_url: str) -> str:
        """
        获取短链接的真实URL
        """
        try:
            response = await self.client.get(short_url)
            return str(response.url)
        except Exception as e:
            raise Exception(f"Failed to resolve short URL: {e}")

    async def parse(self, url: str) -> ProductInfo:
        """
        解析抖音商品链接，返回商品信息和所有图片
        """
        # 处理短链接
        if 'v.douyin.com' in url:
            url = await self.get_real_url(url)

        # 提取商品ID
        product_id = self.extract_product_id(url)
        if not product_id:
            raise ValueError(f"Cannot extract product ID from URL: {url}")

        # 尝试多种方式获取商品数据
        errors = []

        # 方法1: 尝试 jinritemai H5 API
        try:
            result = await self._parse_from_jinritemai_api(product_id)
            if result.main_images or result.detail_images:
                return result
        except Exception as e:
            errors.append(f"jinritemai_api: {e}")

        # 方法2: 尝试原有API
        try:
            result = await self._parse_from_api(product_id)
            if result.main_images or result.detail_images:
                return result
        except Exception as e:
            errors.append(f"api: {e}")

        # 方法3: 尝试移动端页面
        try:
            result = await self._parse_from_mobile_page(product_id)
            if result.main_images or result.detail_images:
                return result
        except Exception as e:
            errors.append(f"mobile_page: {e}")

        # 方法4: 尝试网页解析
        try:
            result = await self._parse_from_webpage(product_id, url)
            if result.main_images or result.detail_images:
                return result
        except Exception as e:
            errors.append(f"webpage: {e}")

        # 方法5: 使用 undetected-chromedriver (最后手段)
        if HAS_UNDETECTED:
            try:
                result = await self._parse_with_undetected(product_id, url)
                if result.main_images or result.detail_images:
                    return result
            except Exception as e:
                errors.append(f"undetected: {e}")

        raise Exception(f"Failed to parse product with all methods: {'; '.join(errors)}")

    async def _parse_from_jinritemai_api(self, product_id: str) -> ProductInfo:
        """
        通过 jinritemai H5 API 获取商品信息
        """
        api_url = f"https://haohuo.jinritemai.com/ecom/product/detail/h5/sc/"

        # 使用移动端 User-Agent
        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': f'https://haohuo.jinritemai.com/views/product/item2?id={product_id}',
            'Origin': 'https://haohuo.jinritemai.com',
        }

        params = {
            'id': product_id,
            'product_id': product_id,
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            response = await client.get(api_url, params=params)

            if response.status_code != 200:
                raise Exception(f"API returned status {response.status_code}")

            data = response.json()

            if data.get('code') != 0 and data.get('status_code') != 0:
                raise Exception(f"API error: {data.get('msg', data.get('message', 'Unknown error'))}")

            product_data = data.get('data', {})
            if not product_data:
                raise Exception("No product data in response")

            return self._extract_product_info(product_data, product_id)

    async def _parse_from_mobile_page(self, product_id: str) -> ProductInfo:
        """
        通过移动端页面获取商品信息
        """
        # 移动端商品页面URL
        url = f"https://haohuo.jinritemai.com/views/product/item2?id={product_id}"

        headers = {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            html = response.text

        # 尝试从页面中提取数据
        product_info = ProductInfo(
            product_id=product_id,
            title="",
            main_images=[],
            detail_images=[],
            sku_images=[]
        )

        # 查找 JSON 数据
        patterns = [
            r'window\.__INITIAL_PROPS__\s*=\s*({.+?});',
            r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
            r'"product"\s*:\s*({.+?})\s*,\s*"',
            r'window\.rawData\s*=\s*({.+?});',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    result = self._extract_from_page_data(data, product_id)
                    if result.main_images:
                        return result
                except json.JSONDecodeError:
                    continue

        # 直接提取图片URL
        image_urls = self._extract_images_from_html(html)

        main_images = []
        detail_images = []

        for i, img_url in enumerate(image_urls):
            img = ProductImage(url=img_url, image_type="main" if i < 5 else "detail")
            if i < 5:
                main_images.append(img)
            else:
                detail_images.append(img)

        product_info.main_images = main_images
        product_info.detail_images = detail_images

        # 提取标题
        title_match = re.search(r'<title>(.+?)</title>', html)
        if title_match:
            product_info.title = title_match.group(1).split('-')[0].strip()

        return product_info

    async def _parse_from_api(self, product_id: str) -> ProductInfo:
        """
        通过API获取商品信息
        """
        # 抖音电商API
        api_url = "https://ec.snssdk.com/product/detail"
        params = {
            'product_id': product_id,
            'aid': '1128',
        }

        response = await self.client.get(api_url, params=params)
        data = response.json()

        if data.get('status_code') != 0:
            raise Exception(f"API error: {data.get('status_msg', 'Unknown error')}")

        product_data = data.get('data', {})
        return self._extract_product_info(product_data, product_id)

    async def _parse_with_undetected(self, product_id: str, url: str) -> ProductInfo:
        """
        使用 undetected-chromedriver 绕过反爬虫检测
        """
        import time

        if not HAS_UNDETECTED:
            raise Exception("undetected-chromedriver not installed")

        def extract_sync():
            options = uc.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=375,812')
            options.add_argument('--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1')

            driver = uc.Chrome(options=options)

            try:
                # 构建URL
                target_url = url
                if 'jinritemai.com' not in url and 'haohuo' not in url:
                    target_url = f"https://haohuo.jinritemai.com/views/product/item2?id={product_id}"

                driver.get(target_url)
                time.sleep(10)  # 等待JS渲染

                page_source = driver.page_source

                # 检查商品是否下架
                if 'product-down' in page_source or '已下架' in page_source:
                    raise Exception("商品已下架或不存在")

                # 提取图片
                images = driver.find_elements(By.TAG_NAME, 'img')
                img_urls = []
                for img in images:
                    src = img.get_attribute('src') or img.get_attribute('data-src')
                    if src and len(src) > 50 and not src.startswith('data:'):
                        if self._is_product_image(src):
                            img_urls.append(src)

                # 提取标题
                title = ""
                try:
                    title_elem = driver.find_element(By.CSS_SELECTOR, 'h1, .product-title, [class*="title"]')
                    title = title_elem.text
                except:
                    pass

                # 提取价格
                price = ""
                try:
                    price_elem = driver.find_element(By.CSS_SELECTOR, '[class*="price"], .price')
                    price = price_elem.text
                except:
                    pass

                return {
                    'title': title,
                    'price': price,
                    'images': img_urls
                }

            finally:
                driver.quit()

        # 在线程池中运行同步代码
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, extract_sync)

        # 分类图片
        main_images = []
        detail_images = []

        for i, img_url in enumerate(result['images']):
            clean_url = self._get_high_quality_url(img_url)
            img = ProductImage(
                url=clean_url,
                image_type="main" if i < 5 else "detail"
            )
            if i < 5:
                main_images.append(img)
            else:
                detail_images.append(img)

        return ProductInfo(
            product_id=product_id,
            title=result.get('title', '').strip(),
            price=result.get('price', '').strip(),
            original_price="",
            shop_name="",
            sales="",
            main_images=main_images,
            detail_images=detail_images,
            sku_images=[],
            video_url=None
        )

    async def _parse_with_playwright(self, url: str, product_id: str) -> ProductInfo:
        """
        使用 Playwright 渲染 JS 页面并提取商品信息
        """
        async with async_playwright() as p:
            # 使用反检测参数
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                ]
            )

            # 设置更真实的浏览器上下文
            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='zh-CN',
            )

            page = await context.new_page()

            # 移除 webdriver 标记
            await page.add_init_script('''
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            ''')

            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)

                # 等待图片加载
                await page.wait_for_timeout(2000)

                # 提取所有图片
                images = await page.evaluate('''() => {
                    const images = [];
                    const imgElements = document.querySelectorAll('img');
                    imgElements.forEach(img => {
                        const src = img.src || img.dataset.src;
                        if (src && (src.includes('ecombdimg') || src.includes('ecombdstatic') ||
                            src.includes('byteimg') || src.includes('tiktokcdn'))) {
                            images.push(src);
                        }
                    });
                    return images;
                }''')

                # 提取标题
                title = await page.evaluate('''() => {
                    const titleEl = document.querySelector('h1, .product-title, [class*="title"]');
                    return titleEl ? titleEl.innerText : '';
                }''')

                # 提取价格
                price = await page.evaluate('''() => {
                    const priceEl = document.querySelector('[class*="price"], .price');
                    return priceEl ? priceEl.innerText : '';
                }''')

            finally:
                await browser.close()

        # 分类图片
        main_images = []
        detail_images = []

        for i, img_url in enumerate(images):
            # 清理URL
            clean_url = self._get_high_quality_url(img_url)
            if not self._is_product_image(clean_url):
                continue

            img = ProductImage(
                url=clean_url,
                image_type="main" if i < 5 else "detail"
            )

            if i < 5:
                main_images.append(img)
            else:
                detail_images.append(img)

        return ProductInfo(
            product_id=product_id,
            title=title.strip() if title else "",
            price=price.strip() if price else "",
            original_price="",
            shop_name="",
            sales="",
            main_images=main_images,
            detail_images=detail_images,
            sku_images=[],
            video_url=None
        )

    async def _parse_from_webpage(self, product_id: str, url: str) -> ProductInfo:
        """
        从网页中提取商品信息
        """
        # 构建商品详情页URL
        if 'haohuo.douyin.com' not in url and 'jinritemai.com' not in url:
            url = f"https://haohuo.douyin.com/goods/{product_id}"

        # 对于 jinritemai.com 使用 Playwright（JS渲染页面）
        if 'jinritemai.com' in url:
            return await self._parse_with_playwright(url, product_id)

        # 使用新的客户端避免代理问题
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30.0) as client:
            response = await client.get(url)
            html = response.text

        # 从页面中提取数据
        product_info = ProductInfo(
            product_id=product_id,
            title="",
            main_images=[],
            detail_images=[],
            sku_images=[]
        )

        # 方法1: 提取 __INITIAL_STATE__ 或类似的JSON数据
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
            r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
            r'window\.__PRELOADED_STATE__\s*=\s*({.+?});',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    product_info = self._extract_from_page_data(data, product_id)
                    if product_info.main_images:
                        return product_info
                except json.JSONDecodeError:
                    continue

        # 方法2: 直接从HTML提取图片URL
        image_urls = self._extract_images_from_html(html)

        # 分类图片
        main_images = []
        detail_images = []

        for i, url in enumerate(image_urls):
            img = ProductImage(url=url, image_type="main" if i < 5 else "detail")
            if i < 5:
                main_images.append(img)
            else:
                detail_images.append(img)

        product_info.main_images = main_images
        product_info.detail_images = detail_images

        # 提取标题
        title_match = re.search(r'<title>(.+?)</title>', html)
        if title_match:
            product_info.title = title_match.group(1).split('-')[0].strip()

        return product_info

    def _extract_images_from_html(self, html: str) -> List[str]:
        """
        从HTML中提取所有商品相关图片URL
        """
        images = []

        # 匹配常见的图片URL模式
        patterns = [
            r'https?://[^"\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\s]*)?',
            r'https?://p\d+-aio\.ecombdstatic\.com/[^"\s]+',
            r'https?://lf\d+-cdn-tos\.tiktokcdn\.com/[^"\s]+',
            r'https?://p\d+-sign\.ecombdstatic\.com/[^"\s]+',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html)
            for url in matches:
                # 过滤掉不相关的图片
                if self._is_product_image(url) and url not in images:
                    # 清理URL，获取高清版本
                    clean_url = self._get_high_quality_url(url)
                    if clean_url not in images:
                        images.append(clean_url)

        return images

    def _is_product_image(self, url: str) -> bool:
        """
        判断URL是否为商品图片
        """
        # 排除图标、logo等
        exclude_keywords = [
            'icon', 'logo', 'avatar', 'emoji', 'sticker',
            'thumb', 'small', '32x32', '64x64', '100x100',
            'favicon', 'sprite'
        ]

        url_lower = url.lower()
        for keyword in exclude_keywords:
            if keyword in url_lower:
                return False

        # 包含商品图片常见域名
        product_domains = [
            'ecombdstatic.com',
            'ecombdimg.com',
            'tiktokcdn.com',
            'byteimg.com',
        ]

        for domain in product_domains:
            if domain in url:
                return True

        return True

    def _get_high_quality_url(self, url: str) -> str:
        """
        获取高清图片URL
        """
        # 移除尺寸限制参数
        url = re.sub(r'~\d+x\d+', '', url)
        url = re.sub(r'\?.*?imageView.*', '', url)

        # 替换为高清版本
        url = re.sub(r'/thumb/', '/origin/', url)
        url = re.sub(r'_\d+x\d+\.', '.', url)

        return url

    def _extract_from_page_data(self, data: dict, product_id: str) -> ProductInfo:
        """
        从页面JSON数据中提取商品信息
        """
        product_info = ProductInfo(
            product_id=product_id,
            title="",
            main_images=[],
            detail_images=[],
            sku_images=[]
        )

        # 递归查找商品数据
        def find_product_data(obj, depth=0):
            if depth > 10:
                return None

            if isinstance(obj, dict):
                # 查找包含商品信息的键
                if 'product' in obj:
                    return obj['product']
                if 'productDetail' in obj:
                    return obj['productDetail']
                if 'goods' in obj:
                    return obj['goods']
                if 'data' in obj and isinstance(obj['data'], dict):
                    result = find_product_data(obj['data'], depth + 1)
                    if result:
                        return result

                for key, value in obj.items():
                    result = find_product_data(value, depth + 1)
                    if result:
                        return result

            elif isinstance(obj, list):
                for item in obj:
                    result = find_product_data(item, depth + 1)
                    if result:
                        return result

            return None

        product_data = find_product_data(data)
        if product_data:
            return self._extract_product_info(product_data, product_id)

        return product_info

    def _extract_product_info(self, product_data: dict, product_id: str) -> ProductInfo:
        """
        从商品数据中提取详细信息
        """
        # 基本信息
        title = product_data.get('name', '') or product_data.get('title', '')
        price = product_data.get('price', {})
        if isinstance(price, dict):
            price_str = price.get('price', '') or price.get('sell_price', '')
        else:
            price_str = str(price) if price else ''

        original_price = product_data.get('market_price', '') or product_data.get('origin_price', '')
        if isinstance(original_price, dict):
            original_price = original_price.get('price', '')

        shop_info = product_data.get('shop', {}) or product_data.get('shop_info', {})
        shop_name = shop_info.get('name', '') or shop_info.get('shop_name', '')

        sales = product_data.get('sales', '') or product_data.get('sold_count', '')

        # 提取主图
        main_images = []
        img_list = product_data.get('img_list', []) or product_data.get('images', []) or product_data.get('main_imgs', [])

        for img in img_list:
            if isinstance(img, str):
                url = img
            elif isinstance(img, dict):
                url = img.get('url', '') or img.get('src', '') or img.get('url_list', [''])[0]
            else:
                continue

            if url:
                main_images.append(ProductImage(
                    url=self._get_high_quality_url(url),
                    image_type="main"
                ))

        # 提取详情图
        detail_images = []
        detail_list = product_data.get('detail_img_list', []) or product_data.get('desc_imgs', []) or product_data.get('detail_images', [])

        for img in detail_list:
            if isinstance(img, str):
                url = img
            elif isinstance(img, dict):
                url = img.get('url', '') or img.get('src', '')
            else:
                continue

            if url:
                detail_images.append(ProductImage(
                    url=self._get_high_quality_url(url),
                    image_type="detail"
                ))

        # 提取SKU图片
        sku_images = []
        sku_list = product_data.get('sku_list', []) or product_data.get('skus', [])

        for sku in sku_list:
            if isinstance(sku, dict):
                sku_img = sku.get('img', '') or sku.get('image', '') or sku.get('thumb_url', '')
                if sku_img:
                    sku_images.append(ProductImage(
                        url=self._get_high_quality_url(sku_img),
                        image_type="sku"
                    ))

        # 提取商品视频
        video_url = None
        video_info = product_data.get('video', {})
        if video_info:
            video_url = video_info.get('url', '') or video_info.get('play_url', '')

        return ProductInfo(
            product_id=product_id,
            title=title,
            price=str(price_str),
            original_price=str(original_price),
            shop_name=shop_name,
            sales=str(sales),
            main_images=main_images,
            detail_images=detail_images,
            sku_images=sku_images,
            video_url=video_url
        )


# 便捷函数
async def parse_douyin_product(url: str) -> ProductInfo:
    """
    解析抖音商品的便捷函数
    """
    parser = DouyinProductParser()
    try:
        return await parser.parse(url)
    finally:
        await parser.close()
