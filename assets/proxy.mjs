// DNS-обход для Termux: локальный HTTP/HTTPS-прокси на c-ares.
//
// Проблема: на некоторых Android-устройствах системный резолвер bionic сломан —
// dns.lookup() (getaddrinfo) висит ~24 с и возвращает ENOTFOUND, тогда как
// dns.resolve4() (c-ares, читает resolv.conf) работает нормально. Из-за этого
// npm падает с ETARGET "No matching version found", хотя версия в реестре есть.
//
// Запись в $PREFIX/etc/hosts НЕ помогает: bionic читает /system/etc/hosts,
// куда без root не записать.
//
// Решение: прокси резолвит имена через c-ares и коннектится по IP.
//
// Запуск (nohup в неинтерактивной SSH-сессии НЕ выживает — нужен setsid):
//   setsid node ~/dnsfix/proxy.mjs > ~/dnsfix/proxy.log 2>&1 < /dev/null &
//   export npm_config_proxy=http://127.0.0.1:8899
//   export npm_config_https_proxy=http://127.0.0.1:8899

import http from "node:http";
import net from "node:net";
import dns from "node:dns";

const PORT = Number(process.env.DNS_PROXY_PORT || 8899);
const HOST = process.env.DNS_PROXY_HOST || "127.0.0.1";

const cache = new Map();

function resolve(host) {
  if (net.isIP(host)) return Promise.resolve(host);
  if (cache.has(host)) return Promise.resolve(cache.get(host));
  return new Promise((res, rej) => {
    dns.resolve4(host, (err, addrs) => {
      if (err || !addrs || !addrs.length) {
        return rej(err || new Error("no A record for " + host));
      }
      cache.set(host, addrs[0]);
      res(addrs[0]);
    });
  });
}

const server = http.createServer((req, res) => {
  (async () => {
    try {
      const url = new URL(req.url);
      const ip = await resolve(url.hostname);
      const port = Number(url.port || 80);
      const upstream = net.connect(port, ip, () => {
        const headers = Object.entries(req.headers)
          .filter(([k]) => k.toLowerCase() !== "proxy-connection")
          .map(([k, v]) => `${k}: ${v}`)
          .join("\r\n");
        upstream.write(
          `${req.method} ${url.pathname}${url.search} HTTP/1.1\r\n${headers}\r\n\r\n`
        );
        req.pipe(upstream);
      });
      upstream.pipe(res);
      upstream.on("error", () => res.destroy());
    } catch {
      res.destroy();
    }
  })();
});

// HTTPS идёт через CONNECT — здесь резолвинг и нужен по-настоящему.
server.on("connect", (req, clientSocket, head) => {
  (async () => {
    try {
      const [host, port] = req.url.split(":");
      const ip = await resolve(host);
      const upstream = net.connect(Number(port || 443), ip, () => {
        clientSocket.write("HTTP/1.1 200 Connection Established\r\n\r\n");
        if (head && head.length) upstream.write(head);
        upstream.pipe(clientSocket);
        clientSocket.pipe(upstream);
      });
      upstream.on("error", () => clientSocket.destroy());
      clientSocket.on("error", () => upstream.destroy());
    } catch {
      clientSocket.destroy();
    }
  })();
});

server.listen(PORT, HOST, () => {
  console.log(`DNS-fix proxy: http://${HOST}:${PORT}`);
});
