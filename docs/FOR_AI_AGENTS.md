# FOR AI AGENTS — alltuu.com (喔图) 系统完整技术规格

> **目标读者：** 其他 AI Agent（Kimi、GPT、Claude 等）
> **文档定位：** 让你读完这份文档后，不需要重新搜索网络，就能独立处理任何 alltuu 相册的下载任务，并能诊断未知问题。
> **版本：** 2026-05-04 | 基于相册 `1461544002`（688 张照片，7 个子相册）的完整逆向工程

---

## 目录

1. [系统架构总览](#1-系统架构总览)
2. [逆向工程方法论](#2-逆向工程方法论)
3. [API 完整规格](#3-api-完整规格)
4. [认证与下载机制](#4-认证与下载机制)
5. [子相册系统](#5-子相册系统)
6. [错误经验录](#6-错误经验录)
7. [新相册诊断 SOP](#7-新相册诊断-sop)
8. [AI 直接调用指南](#8-ai-直接调用指南)

---

## 1. 系统架构总览

### 1.1 前端

- **框架：** Vue 2 单页应用（SPA）
- **页面结构：** 移动端优先，`m.alltuu.com/album/{parentId}/{subAlbumId}?menu=live`
- **图片加载：** 懒加载 + 瀑布流布局
- **子相册切换：** Tab 栏切换不同子相册

### 1.2 API 层

- **Authority API:** `GET /rest/fc/authority/v100002-{ts}-null-0-{sign}?albumId={id}` → 返回 `secret`
- **Album Info API:** `GET /rest/v4c/fa/a{albumId}/sk{secret}/t{ts}` → 返回 `albumDTO` + `seperateDTOList`
- **Photo List API:** `GET /rest/v4c/fplN/a{albumId}/n60/o{offset}/pc/pd/s{subAlbumId}/sk{secret}/t{ts}/v{version}` → 返回 `d[]` 照片数组

### 1.3 存储层（阿里云 OSS）

| 域名 | 用途 | 典型大小 |
|------|------|----------|
| `uis.alltuu.com` | 缩略图 (`sl`) | ~10-50KB |
| `uib.alltuu.com` | 大图 (`bl`) | ~50-100KB |
| `uip.alltuu.com` | 1920px (`url1920`) | ~80-150KB |
| `uio.alltuu.com` | **原图 (`ol`)** | ~2-10MB |

**推荐质量：** `ol` (original large) — 最高质量，带水印但无法去除（去除 `x-oss-process=watermark` 参数会导致 403）

---

## 2. 逆向工程方法论

### 2.1 为什么传统爬虫方法无效

**alltuu 是 SPA，原始 HTML 几乎为空：**
```html
<!DOCTYPE html>
<html>
<head>...</head>
<body><div id="app"></div></body>
</html>
```

**以下方法全部无效：**
- ❌ `requests.get(url).text` 解析 HTML 提取 `<img>`
- ❌ BeautifulSoup / 正则匹配 HTML
- ❌ 直接调用 CDN URL（403 Forbidden）
- ❌ 手动构造 `fplN` API URL（动态 hash 无法预测）

### 2.2 正确方法：分层递进式逆向

#### Step 1 — 用 Playwright 拦截网络请求
```python
page.route("**/*", lambda route, request: capture_api(route, request))
```

**找到的 API：**
```
https://v4c.alltuu.com/{hash}/{ts}/rest/v4c/fplN/a1461544002/n60/o4/pc/pd/s3712671117/sk{secret}/t{ts}/v1
```

#### Step 2 — 分析 API 响应
```json
{
  "d": [
    {
      "i": 1,
      "w": 5996,
      "h": 3998,
      "pc": "pl1DO0FYm3d",
      "n": "3Q5A5985.JPG",
      "ol": "https://uio.alltuu.com/pl1DO0FYm3d.jpg?Expires=...&OSSAccessKeyId=...&Signature=...&x-oss-process=image/watermark,...",
      "bl": "https://uib.alltuu.com/pl1DO0FYm3d.jpg?...",
      "sl": "https://uis.alltuu.com/pl1DO0FYm3d.jpg?...",
      "url1920": "https://uip.alltuu.com/pl1DO0FYm3d.jpg?...",
      "os": 2906730
    }
  ],
  "e": 0,
  "m": "OK"
}
```

#### Step 3 — 尝试直接下载（失败）
```python
import requests
r = requests.get(ol_url)
print(r.status_code)  # 403
```

#### Step 4 — 使用 Playwright `page.evaluate()` + `fetch()`（成功）
```python
result = page.evaluate("""
    async (url) => {
        const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
        return await resp.json();
    }
""", fplN_url)
```

**关键点：** 在浏览器页面上下文中执行 `fetch()`，自动携带正确的 cookie/session。

#### Step 5 — 使用 `page.request.get()` 下载图片（成功）
```python
resp = page.request.get(img_url, timeout=60000)
body = resp.body()
```

**关键点：** `page.request` 复用了 Playwright 浏览器上下文的 cookie，所以能成功下载。

---

## 3. API 完整规格

### 3.1 获取 Secret（Authority API）

```
GET https://m.alltuu.com/rest/fc/authority/v100002-{ts}-null-0-{sign}?albumId={albumId}
```

**响应：**
```json
{
  "d": {
    "secret": "sWp9dyi96e3wzVOjzjz6fJ1bki6Bmu8gMJXxpSCvYXPepitn393b1z4aBk5MuqoAwYROQlYFoe4u99eEymBvifaZcc11hFUKnNFhtsiLs13ypGbsji2DURJM8nC7rZbT"
  },
  "e": 0,
  "m": "OK"
}
```

### 3.2 获取相册信息（Album Info API）

```
GET https://v4c.alltuu.com/{hash}/{ts}/rest/v4c/fa/a{albumId}/sk{secret}/t{ts}
```

**响应字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `d.albumDTO` | object | 父相册信息（title, photoCount 等） |
| `d.seperateDTOList` | array | **子相册列表**，每个元素包含 `idEnc`, `name`, `seq` |

**子相册元素：**
```json
{
  "idEnc": "2173376663",
  "name": "26日选手签到",
  "dsc": "",
  "sortType": 4,
  "seq": 0,
  "kvUrl": null,
  "pcKvUrl": null,
  "enName": "",
  "sepPrivacy": 0
}
```

### 3.3 获取照片列表（Photo List API）

```
GET https://v4c.alltuu.com/{hash}/{ts}/rest/v4c/fplN/a{albumId}/n60/o{offset}/pc/pd/s{subAlbumId}/sk{secret}/t{ts}/v{version}
```

**路径参数：**

| 参数 | 说明 |
|------|------|
| `{hash}` | 动态生成的 hash，每次请求不同，无法预测 |
| `{ts}` | 时间戳（毫秒） |
| `{albumId}` | 父相册 ID |
| `n60` | 每页 60 张 |
| `o{offset}` | 偏移量，从 0 开始 |
| `s{subAlbumId}` | 子相册 ID |
| `sk{secret}` | 从 authority API 获取的 secret |
| `t{ts}` | 时间戳 |
| `v{version}` | 版本号（通常为 1） |

**响应字段（`d` 数组元素）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `i` | int | 索引/排序号 |
| `w` | int | 图片宽度 |
| `h` | int | 图片高度 |
| `pc` | string | 图片 hash ID |
| `n` | string | **原始文件名** |
| `ol` | string | **原图 URL**（最高质量） |
| `bl` | string | 大图 URL |
| `sl` | string | 小图 URL |
| `url1920` | string | 1920px URL |
| `os` | int | **文件大小（字节）** |

### 3.4 分页逻辑

```python
offset = 0
all_photos = []
while True:
    # fplN API URL 包含 o{offset}
    photos = fetch_page(offset)
    if not photos:
        break
    all_photos.extend(photos)
    if len(photos) < 60:
        break
    offset += len(photos)
```

**注意：** 由于 hash 动态变化，不能手动构造分页 URL。必须通过 Playwright 拦截页面加载过程中自动触发的多个 fplN 请求。

---

## 4. 认证与下载机制

### 4.1 为什么必须用 Playwright

**问题：** 三层防护

1. **动态 hash**: `fplN` API URL 包含无法预测的 hash 前缀
2. **Secret 绑定**: `sk{secret}` 与时间戳绑定，过期后失效
3. **CDN 403**: 图片 URL 的 `Signature` 参数与会话绑定

**测试结果：**
- `requests.get(img_url)` → 403 Forbidden
- `page.request.get(img_url)` (同一 Playwright 上下文) → ✅ 200 OK
- `page.evaluate() + fetch(api_url)` → ✅ 200 OK

### 4.2 批量下载策略

**推荐方案：Playwright 页面上下文 `fetch()` + `page.request.get()`**

```python
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) ...",
        viewport={"width": 390, "height": 844},
    )
    page = context.new_page()

    # 1. 拦截 fplN API URL
    fplN_urls = []
    page.route("**/*", lambda r, req: fplN_urls.append(req.url) if "/rest/v4c/fplN/" in req.url else r.continue_())
    
    # 2. 导航并滚动触发 API
    page.goto(album_url)
    for _ in range(20):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)
    
    # 3. 用 page.evaluate() 调用 fetch() 获取照片列表
    result = page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
            return await resp.json();
        }
    """, fplN_urls[0])
    photos = result["d"]
    
    # 4. 用 page.request.get() 下载图片
    for ph in photos:
        resp = page.request.get(ph["ol"])
        with open(ph["n"], "wb") as f:
            f.write(resp.body())
```

### 4.3 断点续传

```python
if filepath.exists():
    existing_size = filepath.stat().st_size
    expected_size = ph.get("os", 0)
    if expected_size and existing_size == expected_size:
        skipped += 1
        continue
```

---

## 5. 子相册系统

### 5.1 子相册自动发现

```python
def fetch_sub_album_list(context):
    page = context.new_page()
    state = {"fa_url": None}
    page.route("**/*", lambda r, req: state.update({"fa_url": req.url}) if "/rest/v4c/fa/a" in req.url else r.continue_())
    page.goto(parent_album_url)
    
    result = page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
            return await resp.json();
        }
    """, state["fa_url"])
    
    subs = result['d'].get('seperateDTOList', [])
    return [{'id': s['idEnc'], 'name': s['name'], 'seq': s['seq']} for s in subs]
```

### 5.2 子相册下载

```python
def download_sub_album(context, sub_album):
    album_url = f"https://m.alltuu.com/album/{parent_id}/{sub_album['id']}?menu=live"
    output_dir = f"{base_dir}/{sub_album['seq']+1:02d}. {sanitize(sub_album['name'])}"
    # ... 下载逻辑
```

---

## 6. 错误经验录

### 6.1 ❌ `route.fetch()` 返回 "Request context disposed"

**现象：** 在 `page.route()` handler 中调用 `route.fetch()` 时失败。

**原因：** 某些版本的 Playwright 中，`route.fetch()` 在特定场景下会触发内部错误。

**解决：** 改用 `route.continue_()` 放行请求，然后使用 `page.evaluate() + fetch()` 在页面上下文中重新获取数据。

### 6.2 ❌ 手动构造 fplN URL 返回 403

**现象：** 用已知的 secret 和 timestamp 手动构造 fplN URL，返回 403。

**原因：** URL 中的 `{hash}` 前缀是动态生成的，每次请求不同，与服务端的某种校验机制绑定。

**解决：** 不要手动构造 URL，始终通过 Playwright 拦截页面触发的真实请求。

### 6.3 ❌ 去除水印参数后 403

**现象：** 从 `ol` URL 中删除 `x-oss-process=image/watermark,...` 后返回 403。

**原因：** 阿里云 OSS 的签名 `Signature` 参数与完整 URL（包括所有查询参数）绑定。

**解决：** 必须下载带水印的原图。目前没有发现有可用的无水印端点。

### 6.4 ❌ 背景任务中 Playwright 输出被缓冲

**现象：** 后台任务运行 Playwright 脚本时，长时间看不到输出。

**解决：** 使用 `python -u`（unbuffered）模式运行脚本，并在所有 `print()` 中添加 `flush=True`。

### 6.5 ❌ 文件编码问题（Windows）

**现象：** PowerShell 输出中文显示为乱码。

**解决：** 这是 PowerShell 的显示问题，实际文件名已正确保存为 UTF-8。用 Python 读取验证：
```python
import os
print(os.listdir(path))  # 显示正确的文件名
```

---

## 7. 新相册诊断 SOP

当遇到未知 alltuu 相册时，按以下步骤排查：

### Step 1 — 确认相册 URL 格式
- 标准格式：`https://m.alltuu.com/album/{parentId}/{subAlbumId}?menu=live`
- 或仅父相册：`https://m.alltuu.com/album/{parentId}`

### Step 2 — 用 Playwright 测试页面加载
```python
page.goto(url, wait_until="domcontentloaded", timeout=30000)
```

### Step 3 — 拦截 fplN API
```python
page.route("**/*", lambda r, req: print(req.url) if "/rest/v4c/fplN/" in req.url else r.continue_())
```

### Step 4 — 测试照片列表获取
```python
result = page.evaluate("""
    async (url) => {
        const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
        return await resp.json();
    }
""", fplN_url)
print(len(result.get("d", [])))
```

### Step 5 — 测试单张图片下载
```python
resp = page.request.get(img_url)
print(resp.status, len(resp.body()))
```

### Step 6 — 检查是否有子相册
```python
# 导航到父相册，拦截 /rest/v4c/fa/a 请求
# 检查响应中的 seperateDTOList
```

---

## 8. AI 直接调用指南

### 8.1 最小可运行示例（单相册）

```python
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ALBUM_URL = "https://m.alltuu.com/album/1461544002/3712671117?menu=live"
OUTPUT_DIR = "./downloads"

Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 ...",
        viewport={"width": 390, "height": 844},
    )
    page = context.new_page()

    # 拦截 fplN API
    state = {"fplN_url": None}
    page.route("**/*", lambda r, req: state.update({"fplN_url": req.url}) or r.continue_() if "/rest/v4c/fplN/" in req.url else r.continue_())
    
    page.goto(ALBUM_URL, wait_until="domcontentloaded", timeout=30000)
    for _ in range(15):
        time.sleep(1)
        if state["fplN_url"]: break
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    # 获取照片列表
    result = page.evaluate("""
        async (url) => {
            const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
            return await resp.json();
        }
    """, state["fplN_url"])
    
    photos = result.get("d", [])
    for ph in photos:
        resp = page.request.get(ph["ol"])
        if resp.status == 200:
            filepath = Path(OUTPUT_DIR) / ph.get("n", "photo.jpg")
            with open(filepath, "wb") as f:
                f.write(resp.body())
    
    browser.close()
```

### 8.2 常见调用模式

**下载单相册：**
```bash
python alltuu_downloader.py
```

**批量下载所有子相册：**
```bash
python alltuu_batch_downloader.py
```

**测试少量照片：**
修改脚本中的 `MAX_RETRIES` 或添加 `break` 逻辑。

---

*Document version: 2026-05-04 | For AI Agents*
