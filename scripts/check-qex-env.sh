#!/bin/bash
# Проверка и запуск окружения для qex (Qdrant + Ollama)

set -e

GREEN='\033[0;32m'
YELLOW='\1[33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}🔍 Проверка окружения для qex (семантический поиск)...${NC}"

# 1. Проверка Qdrant (Docker)
echo -n "Qdrant (Docker): "
if docker ps --format '{{.Names}}' | grep -q "^qdrant$"; then
    echo -e "${GREEN}✅ запущен${NC}"
elif docker ps -a --format '{{.Names}}' | grep -q "^qdrant$"; then
    echo -e "${YELLOW}⚠️  контейнер существует, но остановлен. Запускаем...${NC}"
    docker start qdrant
    echo -e "${GREEN}✅ запущен${NC}"
else
    echo -e "${RED}❌ контейнер qdrant не найден. Создаём...${NC}"
    docker run -d --name qdrant -p 6333:6333 -v qdrant_storage:/qdrant/storage --restart unless-stopped qdrant/qdrant
    echo -e "${GREEN}✅ создан и запущен${NC}"
fi

# 2. Проверка Ollama (глобально)
echo -n "Ollama (глобально): "
if pgrep -x "ollama" > /dev/null; then
    echo -e "${GREEN}✅ запущен (PID $(pgrep -x ollama))${NC}"
else
    echo -e "${YELLOW}⚠️  не запущен. Запускаем...${NC}"
    ollama serve > /tmp/ollama.log 2>&1 &
    sleep 3
    if pgrep -x "ollama" > /dev/null; then
        echo -e "${GREEN}✅ запущен${NC}"
    else
        echo -e "${RED}❌ не удалось запустить. Проверь: ollama --version${NC}"
        exit 1
    fi
fi

# 3. Проверка модели Ollama
MODEL="nomic-embed-text-v2-moe"
echo -n "Модель $MODEL: "
if ollama list | grep -q "$MODEL"; then
    echo -e "${GREEN}✅ уже загружена${NC}"
else
    echo -e "${YELLOW}⚠️  не найдена. Загружаем...${NC}"
    ollama pull $MODEL
    echo -e "${GREEN}✅ загружена${NC}"
fi

# 4. Проверка MCP-сервера qex (опционально)
echo -n "MCP qex (через Claude Code): "
if command -v qex-mcp &> /dev/null; then
    echo -e "${GREEN}✅ найден в PATH${NC}"
else
    echo -e "${YELLOW}⚠️  команда qex-mcp не найдена. Убедись, что MCP сервер добавлен в Claude Code.${NC}"
fi

echo -e "${GREEN}✨ Окружение готово! Можно использовать qex.${NC}"
echo "   Проверка: в Claude Code выполни /mcp и убедись, что qex в статусе connected"