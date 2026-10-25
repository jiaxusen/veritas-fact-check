/* 用户体系前端挂载层：登录/注册/额度显示，自动为 /api/ 请求附加令牌 */
(function () {
  "use strict";
  var KEY = "veritas_user_token";
  function getToken() { try { return localStorage.getItem(KEY) || ""; } catch (e) { return ""; } }
  function setToken(t) { try { t ? localStorage.setItem(KEY, t) : localStorage.removeItem(KEY); } catch (e) {} }
  /* ---- 全局拦截 fetch：自动带 Authorization 头 ---- */
  var _fetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    init = init || {};
    var url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.indexOf("/api/") === 0 || url.indexOf("/api/") > -1) {
      var token = getToken();
      if (token) {
        var headers = new Headers((init && init.headers) || (input && input.headers) || {});
        if (!headers.has("Authorization")) headers.set("Authorization", "Bearer " + token);
        init.headers = headers;
      }
    }
    return _fetch(input, init);
  };
  /* ---- 顶栏 UI ---- */
  function injectUI() {
    var meta = document.querySelector(".topbar-meta");
    if (!meta || document.getElementById("userBar")) return;
    var bar = document.createElement("div");
    bar.id = "userBar";
    bar.style.cssText = "display:flex;align-items:center;gap:8px";
    bar.innerHTML =
      '<span id="quotaBadge" style="display:none;font-size:12px;color:#00E5C0;border:1px solid rgba(0,229,192,.35);border-radius:10px;padding:2px 8px"></span>' +
      '<button id="userBtn" class="btn-ghost tiny" style="cursor:pointer">登录 / 注册</button>';
    meta.insertBefore(bar, meta.firstChild);
    document.getElementById("userBtn").addEventListener("click", onUserBtn);
    refresh();
  }
  function onUserBtn() {
    var token = getToken();
    if (token) {
      if (confirm("已登录。确定退出登录吗？")) {
        _fetch("/api/user/logout", { method: "POST" }).catch(function(){});
        setToken("");
        refresh();
        toast("已退出登录");
      }
      return;
    }
    openModal();
  }
  function openModal() {
    if (document.getElementById("userModal")) return;
    var m = document.createElement("div");
    m.id = "userModal";
    m.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center;z-index:9999";
    m.innerHTML =
      '<div style="width:min(92vw,360px);background:#0E1524;border:1px solid rgba(110,231,183,.25);border-radius:14px;padding:26px 24px;color:#E6F1FF;font-family:inherit">' +
      '<h3 style="margin:0 0 4px;font-size:18px">登录查证台</h3>' +
      '<p style="margin:0 0 16px;font-size:12px;color:#8CA3C7">新用户自动注册，免费版每日 100 次额度</p>' +
      '<input id="umUser" placeholder="用户名（3~20位）" style="width:100%;box-sizing:border-box;margin-bottom:10px;padding:10px 12px;border-radius:8px;border:1px solid rgba(140,163,199,.3);background:#070B14;color:#E6F1FF">' +
      '<input id="umPass" type="password" placeholder="密码（6位以上）" style="width:100%;box-sizing:border-box;margin-bottom:14px;padding:10px 12px;border-radius:8px;border:1px solid rgba(140,163,199,.3);background:#070B14;color:#E6F1FF">' +
      '<button id="umGo" style="width:100%;padding:11px;border:none;border-radius:8px;background:#00E5C0;color:#04121A;font-weight:700;cursor:pointer">登录 / 自动注册</button>' +
      '<p id="umMsg" style="margin:10px 0 0;font-size:12px;color:#FF8A8A;min-height:16px"></p>' +
      '<div style="text-align:right;margin-top:6px"><a href="javascript:void(0)" id="umClose" style="color:#8CA3C7;font-size:12px">关闭</a></div>' +
      "</div>";
    document.body.appendChild(m);
    m.querySelector("#umClose").addEventListener("click", function () { m.remove(); });
    m.querySelector("#umGo").addEventListener("click", doAuth);
    m.querySelector("#umPass").addEventListener("keydown", function (e) { if (e.key === "Enter") doAuth(); });
  }
  function doAuth() {
    var m = document.getElementById("userModal");
    var u = m.querySelector("#umUser").value.trim();
    var p = m.querySelector("#umPass").value;
    var msg = m.querySelector("#umMsg");
    msg.style.color = "#8CA3C7";
    msg.textContent = "提交中…";
    _fetch("/api/user/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u, password: p })
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok && res.j.token) {
          setToken(res.j.token);
          m.remove();
          refresh();
          toast("登录成功，欢迎 " + res.j.user.username);
        } else {
          var detail = (res.j && res.j.detail) || "";
          if (detail.indexOf("不正确") > -1 || detail.indexOf("停用") > -1) {
            msg.style.color = "#FF8A8A"; msg.textContent = detail;
          } else {
            /* 未注册 → 自动注册后再登录 */
            _fetch("/api/user/register", {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ username: u, password: p })
            }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
              .then(function (reg) {
                if (!reg.ok) { msg.style.color = "#FF8A8A"; msg.textContent = (reg.j && reg.j.detail) || "注册失败"; return; }
                return _fetch("/api/user/login", {
                  method: "POST", headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ username: u, password: p })
                }).then(function (r) { return r.json(); })
                  .then(function (j) {
                    if (j.token) { setToken(j.token); m.remove(); refresh(); toast("注册成功，欢迎 " + j.user.username); }
                    else { msg.style.color = "#FF8A8A"; msg.textContent = (j.detail) || "登录失败"; }
                  });
              }).catch(function () { msg.style.color = "#FF8A8A"; msg.textContent = "网络错误，请重试"; });
          }
        }
      }).catch(function () { msg.style.color = "#FF8A8A"; msg.textContent = "网络错误，请重试"; });
  }
  function refresh() {
    var btn = document.getElementById("userBtn");
    var badge = document.getElementById("quotaBadge");
    if (!btn) return;
    var token = getToken();
    if (!token) {
      btn.textContent = "登录 / 注册";
      badge.style.display = "none";
      return;
    }
    _fetch("/api/user/me").then(function (r) {
      if (r.status === 401) { setToken(""); btn.textContent = "登录 / 注册"; badge.style.display = "none"; return null; }
      return r.json();
    }).then(function (j) {
      if (!j || !j.user) return;
      btn.textContent = "👤 " + j.user.username;
      var us = j.usage || {};
      if (typeof us.daily_used === "number") {
        badge.style.display = "";
        badge.textContent = "今日 " + us.daily_used + "/" + us.daily_quota + " 次";
      }
    }).catch(function () {});
  }
  function toast(text) {
    var t = document.getElementById("toast");
    if (t) { t.textContent = text; t.classList.add("show"); setTimeout(function () { t.classList.remove("show"); }, 2600); }
    else { console.log("[user]", text); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", injectUI);
  else injectUI();
})();