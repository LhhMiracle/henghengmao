"""
抖音商品详情页图片解析器
Douyin Product Image Parser - Extract all images from product detail page
"""

import re
import json
import httpx
from typing import List, Optional
from pydantic import BaseModel


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
        try:
            return await self._parse_from_api(product_id)
        except Exception:
            pass

        try:
            return await self._parse_from_webpage(product_id, url)
        except Exception as e:
            raise Exception(f"Failed to parse product: {e}")

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

    async def _parse_from_webpage(self, product_id: str, url: str) -> ProductInfo:
        """
        从网页中提取商品信息
        """
        # 构建商品详情页URL
        if 'haohuo.douyin.com' not in url:
            url = f"https://haohuo.douyin.com/goods/{product_id}"

        response = await self.client.get(url)
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
