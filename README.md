# alltuu-downloader

alltuu.com (喔图) 相册高清原图下载器，支持单相册和批量多子相册下载。

> **核心文件：**
> - `alltuu_downloader.py` — 单相册下载（单文件，AI 可直接调用）
> - `alltuu_batch_downloader.py` — 批量下载父相册下的所有子相册

---

## 快速开始

```bash
pip install requests playwright
playwright install chromium

# 单相册下载
python alltuu_downloader.py

# 批量下载所有子相册
python alltuu_batch_downloader.py
```

---

## 面向 AI 的完整技术文档

**如果你是 AI Agent，请先阅读 [`docs/FOR_AI_AGENTS.md`](docs/FOR_AI_AGENTS.md)**

这份文档包含：
- 完整的逆向工程方法论
- API 详细规格与字段说明
- 认证机制详解（动态 hash + secret）
- Playwright `page.evaluate()` + `fetch()` 下载模式
- 子相册（seperateDTOList）自动发现机制
- 常见错误与诊断流程
- AI 直接调用示例

---

## 功能特性

- **原图下载**: 自动获取 `ol` (original large) 最高质量原图
- **批量子相册**: 自动发现并下载父相册下的所有子相册
- **断点续传**: 已下载的文件自动跳过（按文件大小验证）
- **自动命名**: 按子相册名称创建有序文件夹（如 `01. 26日选手签到`）
- **去重处理**: 文件名冲突自动重命名（`photo_01.jpg`）
- **分页支持**: 自动处理超过 60 张照片的相册分页

---

## 使用方法

### 单相册下载

编辑 `alltuu_downloader.py` 中的配置：

```python
ALBUM_URL = "https://m.alltuu.com/album/1461544002/3712671117?menu=live"
OUTPUT_DIR = r"D:\output"
```

然后运行：
```bash
python alltuu_downloader.py
```

### 批量下载所有子相册

编辑 `alltuu_batch_downloader.py` 中的配置：

```python
PARENT_ALBUM_URL = "https://m.alltuu.com/album/1461544002"
BASE_OUTPUT_DIR = r"D:\output"
```

然后运行：
```bash
python alltuu_batch_downloader.py
```

### 自定义相册 URL

URL 格式：
```
https://m.alltuu.com/album/{parentId}/{subAlbumId}?menu=live
```

- `parentId` — 父相册 ID（如 `1461544002`）
- `subAlbumId` — 子相册 ID（如 `3712671117`）

---

## 技术原理速览

### 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│              m.alltuu.com 前端 (Vue SPA)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   ┌─────────┐      ┌─────────────┐    ┌─────────────┐
   │ /rest/  │      │ /rest/v4c/  │    │  Aliyun     │
   │ fc/     │      │ fplN/       │    │  OSS CDN    │
   │authority│      │ 照片列表 API │    │ uio.alltuu  │
   │ 获取    │      │ 返回 d[]    │    │ .com        │
   │ secret  │      │ 含 ol/bl/sl │    │ (原图)      │
   └─────────┘      └─────────────┘    └─────────────┘
```

### 关键发现

1. **动态 hash**: `fplN` API URL 包含动态生成的 hash 前缀，每次请求不同
2. **Secret 绑定**: `sk{secret}` 参数从 `authority` API 获取，与时间戳绑定
3. **403 防护**: 直接 `requests.get()` 访问图片 URL 返回 403
4. **下载方案**: Playwright `page.evaluate()` 在浏览器上下文中执行 `fetch()`，复用 session
5. **子相册**: 父相册通过 `seperateDTOList` 返回所有子相册信息

---

## 文件说明

| 文件 | 说明 |
|------|------|
| `alltuu_downloader.py` | 单相册下载脚本 |
| `alltuu_batch_downloader.py` | 批量子相册下载脚本 |
| `README.md` | 人类用户快速入口 |
| `docs/FOR_AI_AGENTS.md` | **AI 必读**：完整技术规格、错误经验、诊断流程 |

---

*Created by XHJ-Studio | 2026-05-04*
