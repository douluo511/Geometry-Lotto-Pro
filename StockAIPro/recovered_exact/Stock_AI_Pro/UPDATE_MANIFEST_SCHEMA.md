# Signed Update Manifest — Updater 1.2

4.3+ 正式发布推荐使用 Schema 2：

```json
{
  "manifest_schema_version": 2,
  "product": "Stock AI Pro",
  "version": "4.3.1",
  "release_id": "stock-ai-pro-4.3.1-20260910-001",
  "min_updater_version": "1.2.0",
  "mandatory": false,
  "require_internal_manifest": true,
  "package_url": "https://example.com/releases/Stock_AI_Pro_4.3.1.zip",
  "size": 12345678,
  "sha256": "64-hex-sha256",
  "signature": "base64-ed25519-signature"
}
```

安全规则：

- `signature` 对删除 `signature` 后的 canonical JSON 使用 Ed25519 签名；客户端只内置公钥，私钥绝不进入用户包。
- 自动更新只允许严格高于当前活动版本；相同版本和降级包一律拒绝，人工回滚只走本地 rollback 状态机。
- Schema 2 要求新版目录包含 `PACKAGE_MANIFEST.json`，Updater 会逐文件验证内部受控文件 SHA-256。
- `release_id` 必须唯一；Health Check 失败并回滚的 release_id 会进入失败清单，避免同一坏版本重复安装。
- `min_updater_version` 阻止旧 Updater 安装其无法安全处理的包。
- 远程 Manifest 与最终下载 URL 都必须保持 HTTPS；如果 HTTPS 请求被重定向到非 HTTPS，直接拒绝。
- 下载前执行磁盘空间预检和下载体积上限；解压前执行路径穿越、符号链接、文件数量、总解压体积和异常压缩比检查。
- 包内 `VERSION` 必须与签名 Manifest 的 `version` 一致。
- staging、版本安装、current.json 切换和 journal 均使用事务化流程；失败保持旧版本或回滚。
