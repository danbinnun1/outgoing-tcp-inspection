#define _GNU_SOURCE
#include <arpa/inet.h>
#include <linux/netfilter_ipv4.h>
#include <netinet/in.h>
#include <netinet/ip.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#define PORT 5000
#define BUF 8192

static void pump(int in, int out) {
    char buf[BUF];
    ssize_t n;
    while ((n = read(in, buf, BUF)) > 0) {
        write(out, buf, n);
        write(STDOUT_FILENO, buf, n);
    }
}

int main(int argc, char *argv[]) {
    int lstn = socket(AF_INET, SOCK_STREAM, 0);
    if (lstn < 0) {
        perror("socket");
        return 1;
    }

    int one = 1;
    setsockopt(lstn, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    setsockopt(lstn, SOL_IP, IP_TRANSPARENT, &one, sizeof(one));

    struct sockaddr_in bind_addr = {
        .sin_family = AF_INET,
        .sin_port = htons(PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY)
    };
    if (bind(lstn, (void*)&bind_addr, sizeof(bind_addr)) < 0) {
        perror("bind");
        return 1;
    }
    if (listen(lstn, 128) < 0) {
        perror("listen");
        return 1;
    }

    while (1) {
        int cli = accept(lstn, NULL, NULL);
        if (cli < 0) continue;

        struct sockaddr_in dst;
        socklen_t len = sizeof(dst);
        if (argc >= 3) {
            memset(&dst, 0, sizeof(dst));
            dst.sin_family = AF_INET;
            dst.sin_port = htons(atoi(argv[2]));
            if (inet_pton(AF_INET, argv[1], &dst.sin_addr) <= 0) {
                close(cli);
                continue;
            }
        } else {
            if (getsockopt(cli, SOL_IP, SO_ORIGINAL_DST, &dst, &len) != 0) {
                perror("getsockopt");
                close(cli);
                continue;
            }
        }

        int srv = socket(AF_INET, SOCK_STREAM, 0);
        if (srv < 0) {
            close(cli);
            continue;
        }
        setsockopt(srv, SOL_IP, IP_TRANSPARENT, &one, sizeof(one));
        if (connect(srv, (void*)&dst, sizeof(dst)) < 0) {
            close(cli); close(srv); continue;
        }
        if (!fork()) {
            pump(cli, srv);
            _exit(0);
        }
        close(cli); close(srv);
    }
}
