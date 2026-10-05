# 发布流程（固定约定）

每次改动 `standalone.html` 后，必须发布到以下两个位置：

## 1. GitHub Pages
- 仓库：`fred-chen/longctx-bench`（public）
- 提交并推送：
  ```bash
  git add standalone.html && git commit -m "..." && git push
  ```
- 线上地址：**https://fred-chen.github.io/longctx-bench/standalone.html**
- Pages 构建约需 30-60 秒

## 2. NAS nginx 静态目录
```bash
scp standalone.html root@nas.chenp.net:/usr/share/nginx/html/longctx.html
ssh root@nas.chenp.net 'chmod 644 /usr/share/nginx/html/longctx.html'
```
- 线上地址：**http://nas.chenp.net/longctx.html**
- 注意：scp 默认权限 600 会导致 nginx 403，**必须 chmod 644**

## 验证命令
```bash
md5 -q standalone.html
curl -s http://nas.chenp.net/longctx.html | md5
curl -s https://fred-chen.github.io/longctx-bench/standalone.html | md5
```
三个 md5 一致即发布成功。
