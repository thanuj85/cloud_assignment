# Subnetting 10.20.0.0/16

The block `10.20.0.0/16` holds `2^16 = 65,536` addresses. The four subnets are placed in
order of decreasing size, each starting at the first free address after the previous one,
and each uses the smallest prefix whose usable host count fits the requirement
(`usable = 2^(32-prefix) - 2`).

## Working

| Subnet | Hosts needed | Smallest prefix that fits | Block size | Addresses used |
|---|---|---|---|---|
| app | 1,000 | `/22` → 2^10 − 2 = 1,022 | 1,024 | 10.20.0.0 – 10.20.3.255 |
| public | 250 | `/24` → 2^8 − 2 = 254 | 256 | 10.20.4.0 – 10.20.4.255 |
| data | 100 | `/25` → 2^7 − 2 = 126 | 128 | 10.20.5.0 – 10.20.5.127 |
| management | 20 | `/27` → 2^5 − 2 = 30 | 32 | 10.20.5.128 – 10.20.5.159 |

`/23` gives only 510 hosts for app, so `/22` is the smallest prefix that fits 1,000.
`/26` gives 62 hosts for data (too few), and `/28` gives 14 for management (too few).

Allocation is sequential from 10.20.0.0: app fills 10.20.0.0/22, public starts at
10.20.4.0, data starts at 10.20.5.0, and management starts at 10.20.5.128.
Total used: 1,024 + 256 + 128 + 32 = 1,440 addresses; 10.20.5.160 onwards stays free.

## Subnet table

| Subnet | Network address | Prefix | Usable host range | Broadcast | Usable hosts |
|---|---|---|---|---|---|
| app | 10.20.0.0 | /22 | 10.20.0.1 – 10.20.3.254 | 10.20.3.255 | 1,022 |
| public | 10.20.4.0 | /24 | 10.20.4.1 – 10.20.4.254 | 10.20.4.255 | 254 |
| data | 10.20.5.0 | /25 | 10.20.5.1 – 10.20.5.126 | 10.20.5.127 | 126 |
| management | 10.20.5.128 | /27 | 10.20.5.129 – 10.20.5.158 | 10.20.5.159 | 30 |

## Why a stateless NACL needs explicit reply rules

A network ACL inspects each packet on its own and keeps no connection table, so the
return packets of an allowed connection are not exempt from the rules. A reply from a
server to a client has the client's ephemeral port (1024–65535) as its *destination*
port. Both directions therefore need their own rule: inbound reply traffic from the app
subnet (rule 140) and outbound reply traffic to clients (rule 110). Without them a
connection would be permitted in one direction only and the replies would hit the
implicit deny.

The `198.51.100.0/24` deny is rule **100**, lower than the web allow rules (110, 120).
A NACL evaluates rules from the lowest number upwards and stops at the first match, so
the deny only overrides "allow TCP 443 from anywhere" because it is evaluated first. If
it were numbered above those rules, HTTPS from the abusive range would be allowed and the
deny would never be reached. See `network/nacl.json`.
