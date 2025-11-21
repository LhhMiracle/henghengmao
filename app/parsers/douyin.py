"""
抖音视频解析器 - 提取无水印视频
Douyin Video Parser - Extract video without watermark
"""

import re
import json
import httpx
from typing import Optional
from pydantic import BaseModel


class VideoInfo(BaseModel):
    """视频信息模型"""
    video_id: str
    title: str
    author: str
    author_id: str
    cover_url: str
    video_url: str  # 无水印视频链接
    music_url: Optional[str] = None
    duration: int = 0
    create_time: int = 0
    statistics: dict = {}


class DouyinVideoParser:
    """抖音视频解析器"""

    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.douyin.com/',
            'Accept': 'application/json, text/plain, */*',
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

    def extract_video_id(self, url: str) -> Optional[str]:
        """
        从各种抖音链接格式中提取视频ID
        支持格式:
        - https://www.douyin.com/video/7123456789012345678
        - https://v.douyin.com/xxxxxx/
        - https://www.iesdouyin.com/share/video/7123456789012345678
        """
        # 标准视频链接
        match = re.search(r'/video/(\d+)', url)
        if match:
            return match.group(1)

        # 短链接中的ID
        match = re.search(r'modal_id=(\d+)', url)
        if match:
            return match.group(1)

        # note格式
        match = re.search(r'/note/(\d+)', url)
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

    async def parse(self, url: str) -> VideoInfo:
        """
        解析抖音视频链接，返回视频信息
        """
        # 处理短链接
        if 'v.douyin.com' in url or 'vm.tiktok.com' in url:
            url = await self.get_real_url(url)

        # 提取视频ID
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError(f"Cannot extract video ID from URL: {url}")

        # 调用抖音API获取视频详情
        api_url = f"https://www.douyin.com/aweme/v1/web/aweme/detail/"
        params = {
            'aweme_id': video_id,
            'aid': '6383',
            'cookie_enabled': 'true',
            'platform': 'PC',
        }

        try:
            response = await self.client.get(api_url, params=params)
            data = response.json()
        except Exception as e:
            # 备用方案：从网页中提取数据
            return await self._parse_from_webpage(video_id)

        if data.get('status_code') != 0:
            # 尝试备用方案
            return await self._parse_from_webpage(video_id)

        aweme_detail = data.get('aweme_detail', {})
        if not aweme_detail:
            raise Exception("Failed to get video details")

        return self._extract_video_info(aweme_detail)

    async def _parse_from_webpage(self, video_id: str) -> VideoInfo:
        """
        从网页中提取视频信息（备用方案）
        """
        page_url = f"https://www.douyin.com/video/{video_id}"

        try:
            response = await self.client.get(page_url)
            html = response.text

            # 从页面中提取 RENDER_DATA
            match = re.search(r'<script id="RENDER_DATA" type="application/json">(.+?)</script>', html)
            if match:
                import urllib.parse
                render_data = urllib.parse.unquote(match.group(1))
                data = json.loads(render_data)

                # 遍历找到视频数据
                for key, value in data.items():
                    if isinstance(value, dict) and 'aweme' in value:
                        aweme_detail = value['aweme']['detail']
                        return self._extract_video_info(aweme_detail)

            raise Exception("Cannot find video data in webpage")

        except Exception as e:
            raise Exception(f"Failed to parse from webpage: {e}")

    def _extract_video_info(self, aweme_detail: dict) -> VideoInfo:
        """
        从aweme_detail中提取视频信息
        """
        video_id = aweme_detail.get('aweme_id', '')

        # 获取视频描述/标题
        title = aweme_detail.get('desc', '') or aweme_detail.get('title', '')

        # 获取作者信息
        author_info = aweme_detail.get('author', {})
        author = author_info.get('nickname', '')
        author_id = author_info.get('uid', '') or author_info.get('sec_uid', '')

        # 获取封面
        cover = aweme_detail.get('video', {}).get('cover', {})
        cover_url = ''
        if cover:
            url_list = cover.get('url_list', [])
            if url_list:
                cover_url = url_list[0]

        # 获取无水印视频链接
        video_url = self._get_no_watermark_url(aweme_detail)

        # 获取音乐链接
        music_info = aweme_detail.get('music', {})
        music_url = ''
        if music_info:
            play_url = music_info.get('play_url', {})
            if play_url:
                url_list = play_url.get('url_list', [])
                if url_list:
                    music_url = url_list[0]

        # 获取视频时长
        duration = aweme_detail.get('video', {}).get('duration', 0)

        # 获取创建时间
        create_time = aweme_detail.get('create_time', 0)

        # 获取统计数据
        statistics = aweme_detail.get('statistics', {})
        stats = {
            'digg_count': statistics.get('digg_count', 0),  # 点赞数
            'comment_count': statistics.get('comment_count', 0),  # 评论数
            'share_count': statistics.get('share_count', 0),  # 分享数
            'collect_count': statistics.get('collect_count', 0),  # 收藏数
        }

        return VideoInfo(
            video_id=video_id,
            title=title,
            author=author,
            author_id=author_id,
            cover_url=cover_url,
            video_url=video_url,
            music_url=music_url,
            duration=duration,
            create_time=create_time,
            statistics=stats
        )

    def _get_no_watermark_url(self, aweme_detail: dict) -> str:
        """
        获取无水印视频链接
        """
        video_info = aweme_detail.get('video', {})

        # 方法1: 从 play_addr 获取
        play_addr = video_info.get('play_addr', {})
        if play_addr:
            url_list = play_addr.get('url_list', [])
            for url in url_list:
                # 替换水印参数
                if 'watermark' in url:
                    url = url.replace('watermark=1', 'watermark=0')
                # 优先选择无水印域名
                if 'aweme.snssdk.com' in url or 'v.douyin.com' not in url:
                    return url
            if url_list:
                return url_list[0].replace('watermark=1', 'watermark=0')

        # 方法2: 从 bit_rate 获取高清链接
        bit_rate = video_info.get('bit_rate', [])
        if bit_rate:
            # 选择最高码率
            sorted_rates = sorted(bit_rate, key=lambda x: x.get('bit_rate', 0), reverse=True)
            for rate in sorted_rates:
                play_addr = rate.get('play_addr', {})
                url_list = play_addr.get('url_list', [])
                if url_list:
                    return url_list[0].replace('watermark=1', 'watermark=0')

        # 方法3: 从 download_addr 获取
        download_addr = video_info.get('download_addr', {})
        if download_addr:
            url_list = download_addr.get('url_list', [])
            if url_list:
                return url_list[0]

        raise Exception("Cannot find video URL")


# 便捷函数
async def parse_douyin_video(url: str) -> VideoInfo:
    """
    解析抖音视频的便捷函数
    """
    parser = DouyinVideoParser()
    try:
        return await parser.parse(url)
    finally:
        await parser.close()
