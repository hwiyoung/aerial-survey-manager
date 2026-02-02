#!/bin/bash
#
# 네트워크 고정 IP 설정 스크립트
# Ubuntu Desktop (NetworkManager) 및 Ubuntu Server (Netplan) 지원
#

set -e

# 색상 정의
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=============================================="
echo "     네트워크 고정 IP 설정"
echo "==============================================${NC}"
echo ""

# 현재 네트워크 정보 표시
echo -e "${YELLOW}현재 네트워크 상태:${NC}"
echo "-------------------------------------------"
ip -4 addr show | grep -E "inet |^[0-9]:" | head -20
echo "-------------------------------------------"
echo ""

# NetworkManager 또는 Netplan 감지
if command -v nmcli &> /dev/null && systemctl is-active --quiet NetworkManager; then
    NETWORK_MANAGER="nmcli"
    echo -e "감지된 네트워크 관리자: ${GREEN}NetworkManager${NC}"

    # 현재 연결 목록
    echo ""
    echo -e "${YELLOW}현재 연결 목록:${NC}"
    nmcli connection show
    echo ""
elif [ -d /etc/netplan ]; then
    NETWORK_MANAGER="netplan"
    echo -e "감지된 네트워크 관리자: ${GREEN}Netplan${NC}"
else
    echo -e "${RED}지원되는 네트워크 관리자를 찾을 수 없습니다.${NC}"
    exit 1
fi

# 인터페이스 선택
echo ""
echo -e "${YELLOW}네트워크 인터페이스 목록:${NC}"
ip link show | grep -E "^[0-9]:" | awk -F': ' '{print $2}' | grep -v "lo"
echo ""

read -p "설정할 인터페이스 이름 (예: enp0s31f6, eth0): " INTERFACE

if [ -z "$INTERFACE" ]; then
    echo -e "${RED}인터페이스 이름이 필요합니다.${NC}"
    exit 1
fi

# IP 주소 입력
echo ""
read -p "고정 IP 주소 (예: 192.168.0.100): " IP_ADDRESS
read -p "서브넷 마스크 CIDR (예: 24): " SUBNET
read -p "게이트웨이 (예: 192.168.0.1): " GATEWAY
read -p "DNS 서버 (예: 8.8.8.8): " DNS

# 기본값 설정
SUBNET=${SUBNET:-24}
DNS=${DNS:-8.8.8.8}

# 입력 확인
echo ""
echo -e "${YELLOW}설정 확인:${NC}"
echo "-------------------------------------------"
echo "인터페이스: $INTERFACE"
echo "IP 주소: $IP_ADDRESS/$SUBNET"
echo "게이트웨이: $GATEWAY"
echo "DNS: $DNS"
echo "-------------------------------------------"
echo ""

read -p "이 설정을 적용하시겠습니까? (y/N): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo "취소되었습니다."
    exit 0
fi

# 설정 적용
if [ "$NETWORK_MANAGER" = "nmcli" ]; then
    echo ""
    echo -e "${BLUE}NetworkManager로 설정 적용 중...${NC}"

    # 연결 이름 찾기
    CONNECTION_NAME=$(nmcli -t -f NAME,DEVICE connection show | grep ":$INTERFACE$" | cut -d: -f1)

    if [ -z "$CONNECTION_NAME" ]; then
        echo -e "${RED}인터페이스 $INTERFACE에 연결된 연결을 찾을 수 없습니다.${NC}"
        echo "사용 가능한 연결:"
        nmcli connection show
        exit 1
    fi

    echo "연결 이름: $CONNECTION_NAME"

    # 고정 IP 설정
    sudo nmcli connection modify "$CONNECTION_NAME" \
        ipv4.addresses "$IP_ADDRESS/$SUBNET" \
        ipv4.gateway "$GATEWAY" \
        ipv4.dns "$DNS" \
        ipv4.method manual

    echo ""
    echo -e "${YELLOW}경고: 연결을 재시작하면 SSH 연결이 끊길 수 있습니다.${NC}"
    read -p "연결을 재시작하시겠습니까? (y/N): " RESTART

    if [[ "$RESTART" =~ ^[Yy]$ ]]; then
        echo "연결 재시작 중..."
        sudo nmcli connection down "$CONNECTION_NAME" && sudo nmcli connection up "$CONNECTION_NAME"
    else
        echo ""
        echo -e "${YELLOW}나중에 다음 명령어로 적용하세요:${NC}"
        echo "sudo nmcli connection down \"$CONNECTION_NAME\" && sudo nmcli connection up \"$CONNECTION_NAME\""
    fi

elif [ "$NETWORK_MANAGER" = "netplan" ]; then
    echo ""
    echo -e "${BLUE}Netplan 설정 파일 생성 중...${NC}"

    NETPLAN_FILE="/etc/netplan/99-static-ip.yaml"

    sudo tee "$NETPLAN_FILE" > /dev/null << EOF
# 고정 IP 설정 - Aerial Survey Manager
network:
  version: 2
  ethernets:
    $INTERFACE:
      addresses:
        - $IP_ADDRESS/$SUBNET
      routes:
        - to: default
          via: $GATEWAY
      nameservers:
        addresses:
          - $DNS
EOF

    echo "설정 파일 생성됨: $NETPLAN_FILE"

    echo ""
    echo -e "${YELLOW}경고: 설정을 적용하면 SSH 연결이 끊길 수 있습니다.${NC}"
    read -p "Netplan 설정을 적용하시겠습니까? (y/N): " APPLY

    if [[ "$APPLY" =~ ^[Yy]$ ]]; then
        echo "Netplan 적용 중..."
        sudo netplan apply
    else
        echo ""
        echo -e "${YELLOW}나중에 다음 명령어로 적용하세요:${NC}"
        echo "sudo netplan apply"
    fi
fi

echo ""
echo -e "${GREEN}=============================================="
echo "     설정 완료!"
echo "==============================================${NC}"
echo ""
echo "설정 확인:"
ip addr show "$INTERFACE"
echo ""

# hosts 파일 안내
echo -e "${YELLOW}클라이언트 PC의 hosts 파일에 다음을 추가하세요:${NC}"
echo ""
echo "  $IP_ADDRESS    ortho.local"
echo ""
echo "  - Linux/Mac: /etc/hosts"
echo "  - Windows: C:\\Windows\\System32\\drivers\\etc\\hosts"
echo ""
