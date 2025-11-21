"""
Henghengmao - 视频解析与图片下载服务
Video Parser & Image Downloader Service
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from app.parsers.douyin import DouyinVideoParser, VideoInfo
from app.parsers.douyin_product import DouyinProductParser, ProductInfo

# 创建 FastAPI 应用
app = FastAPI(
    title="Henghengmao",
    description="抖音视频解析与商品图片下载服务",
    version="1.0.0"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# 请求模型
class ParseRequest(BaseModel):
    url: str


# API 路由

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/video/parse", response_model=VideoInfo)
async def parse_video(req: ParseRequest):
    """
    解析视频链接，返回无水印视频信息

    支持平台:
    - 抖音 (douyin.com, v.douyin.com)
    """
    url = req.url.strip()

    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    # 判断平台并解析
    if 'douyin.com' in url or 'iesdouyin.com' in url:
        parser = DouyinVideoParser()
        try:
            result = await parser.parse(url)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")
        finally:
            await parser.close()
    else:
        raise HTTPException(status_code=400, detail="暂不支持该平台，目前仅支持抖音")


@app.post("/api/product/parse", response_model=ProductInfo)
async def parse_product(req: ParseRequest):
    """
    解析商品链接，返回所有图片

    支持平台:
    - 抖音商品 (haohuo.douyin.com, douyin.com/goods)
    """
    url = req.url.strip()

    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    # 判断平台并解析
    if 'douyin.com' in url or 'jinritemai.com' in url:
        parser = DouyinProductParser()
        try:
            result = await parser.parse(url)
            return result
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"解析失败: {str(e)}")
        finally:
            await parser.close()
    else:
        raise HTTPException(status_code=400, detail="暂不支持该平台，目前仅支持抖音商品")


@app.get("/api/proxy")
async def proxy_download(url: str, filename: str = "download"):
    """
    代理下载文件（解决跨域和防盗链问题）
    """
    import urllib.parse

    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.douyin.com/',
    }

    async def stream_response():
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream('GET', url, headers=headers) as response:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    yield chunk

    # 根据URL判断文件类型
    content_type = 'application/octet-stream'
    if '.mp4' in url or 'video' in url:
        content_type = 'video/mp4'
        if not filename.endswith('.mp4'):
            filename += '.mp4'
    elif '.jpg' in url or '.jpeg' in url:
        content_type = 'image/jpeg'
        if not filename.endswith(('.jpg', '.jpeg')):
            filename += '.jpg'
    elif '.png' in url:
        content_type = 'image/png'
        if not filename.endswith('.png'):
            filename += '.png'
    elif '.webp' in url:
        content_type = 'image/webp'
        if not filename.endswith('.webp'):
            filename += '.webp'

    # 处理中文文件名 - 使用 RFC 5987 编码
    encoded_filename = urllib.parse.quote(filename)

    return StreamingResponse(
        stream_response(),
        media_type=content_type,
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"
        }
    )


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "message": "服务正常运行"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
