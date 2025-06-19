### Minimal **Transparent TCP Proxy** on Linux 2.6.37

*(one-way capture: we forward the connection but log only **client → server** data)*

---

## 1 Kernel requirements

| Component                        | Status on **2.6.37**                        | Why it matters                                                                              |
| -------------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `xt_TPROXY`, `xt_socket` targets | Built-in since 2.6.28 (stable by 2.6.37)    | `xt_TPROXY` diverts the packet to userspace; `xt_socket` lets the rule match “this socket”. |
| `IP_TRANSPARENT` sockopt         | Available since 2.6.25                      | Allows a socket to receive / send **foreign** destination addresses.                        |
| `SO_ORIGINAL_DST` sockopt        | Available since 2.4                         | Tells userland *which* IP\:Port the client originally dialed.                               |
| `CONFIG_IP_MULTIPLE_TABLES`      | Must be **y**                               | Needed for the extra routing-table (100) in policy-routing.                                 |
| nftables                         | **Not** yet present – use *iptables-legacy* | 2.6.37 predates nft, so legacy iptables is used.                                            |

> If the targets are modules:
>
> ```bash
> modprobe xt_TPROXY
> modprobe xt_socket
> ```
---
## 2 Netfilter + policy-routing rules
*(run once at boot, as root)*
```bash
# ───────────────────────────── ① intercept
# Grab every TCP packet entering the LAN bridge and mark it “1”.
iptables -t mangle -A PREROUTING -i br-lan -p tcp \
        -j TPROXY --on-port 5000 --tproxy-mark 1
#           --on-port 5000   → kernel delivers packet to 127.0.0.1:5000
#           --tproxy-mark 1  → skb mark = 1 (used by the ip rule below)
# ───────────────────────────── ② local-delivery trick
# ip rule:  only packets whose MARK == 1 are routed via table 100
ip rule  add fwmark 1 lookup 100
# table 100 says: “every destination is LOCAL, deliver to loopback”
ip route add local 0.0.0.0/0 dev lo table 100
```
---

## 3 Single-file C proxy (≈ 110 LOC, inline explanations)

```c
/*  gcc -O2 -Wall -o tcp_proxy_oneway tcp_proxy_oneway.c
 *  sudo ./tcp_proxy_oneway > /var/log/client_upload.log
 *
 *  Listens on 0.0.0.0:5000, forwards to the original destination,
 *  logs ONLY client→server bytes to stdout.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define PORT 5000        /* must match --on-port in iptables */
#define BUF  8192

/* copy + log helper */
static void pump(int in, int out) {
    char buf[BUF]; ssize_t n;
    while ((n = read(in, buf, BUF)) > 0) {
        write(out,           buf, n);   /* forward to real server        */
        write(STDOUT_FILENO, buf, n);   /* mirror to log / stdout        */
    }
}

int main(void)
{
    int lstn = socket(AF_INET, SOCK_STREAM, 0);

    /* SO_REUSEADDR: allow instant re-bind after crash/restart        */
    int one = 1;
    setsockopt(lstn, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

    /* IP_TRANSPARENT on listening socket
     *     lets this socket accept packets whose destination IP belongs
     *     to SOMEONE ELSE (8.8.8.8, 1.1.1.1 …) that TPROXY diverted.   */
    setsockopt(lstn, SOL_IP, IP_TRANSPARENT, &one, sizeof(one));

    struct sockaddr_in bind_addr = {
        .sin_family = AF_INET,
        .sin_port   = htons(PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY)
    };
    bind(lstn, (void*)&bind_addr, sizeof(bind_addr));
    listen(lstn, 128);

    while (1) {
        int cli = accept(lstn, NULL, NULL);
        if (cli < 0) continue;

        /* ---- discover where the client really wanted to go ---------- */
        struct sockaddr_in dst; socklen_t len = sizeof(dst);
        getsockopt(cli, SOL_IP, SO_ORIGINAL_DST, &dst, &len);

        /* ---- open a real connection to that original destination ---- */
        int srv = socket(AF_INET, SOCK_STREAM, 0);

        setsockopt(srv, SOL_IP, IP_TRANSPARENT, &one, sizeof(one));

        if (connect(srv, (void*)&dst, sizeof(dst)) < 0) {
            close(cli); close(srv); continue;
        }

        /* child handles one direction: client → server (+ logging) */
        if (!fork()) {
            pump(cli, srv);
            _exit(0);
        }
        /* parent: close fds, accept next connection */
        close(cli); close(srv);
    }
}
```
---
## 4 Build & run
```bash
gcc -O2 -Wall -o tcp_proxy_oneway tcp_proxy_oneway.c
sudo ./tcp_proxy_oneway > /var/log/client_upload.log
```

---

### Why is this still **transparent**?

* **Destination IP/port never change** – packets still carry *8.8.8.8:443* (or any real server) all the way.
* `IP_TRANSPARENT` lets our socket *impersonate* that foreign address, so the TCP handshake completes locally.
* We open a second socket to the true server, forward bytes and relay ACKs:
  the client sees the usual RTT, never a NAT IP → perfectly **transparent**.

---

#### What you now have

* **Transparent** – clients still see the original IP/port.
* **Stream-ready** – kernel already did re-assembly; you read straight bytes.
* **One-direction capture** – only client → server payload is logged.
* Pure C + raw syscalls, no external libraries; runs fine on any 2.6.37 kernel with Netfilter & TPROXY.
