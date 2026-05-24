# -*- coding: utf-8 -*-
"""
Asynchronous proxy management module
- Asynchronous proxy testing
- Non-blocking batch processing
- asyncio-based implementation
"""

import asyncio
import aiohttp
import datetime
import re
import time
import random
from typing import List, Optional, Tuple, AsyncGenerator
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .models import ProxyStatus, UserProxy, StatusEnum
from .db import get_db


class ProxyManager:
    """Asynchronous proxy manager"""

    def __init__(self):
        self.proxy_cache = {}
        self.cache_timeout = 300  # 5 minutes
        self.current_proxy_index = 0
        self.failed_count = 0
        self.download_proxy_index = {}  # per-download proxy index management
        self._proxy_lock = asyncio.Lock()  # protect concurrent access during proxy selection

    async def get_user_proxy_list(self, db: Session) -> List[str]:
        """Fetch the user's proxy list asynchronously"""
        user_proxies = db.query(UserProxy).filter(UserProxy.is_active == True).all()
        proxy_list = []

        # Process URL-type proxies asynchronously
        url_proxies = [p for p in user_proxies if p.proxy_type == "list"]
        single_proxies = [p.address for p in user_proxies if p.proxy_type == "single"]

        # Add single proxies directly
        proxy_list.extend(single_proxies)

        # Process URL proxies asynchronously in parallel
        if url_proxies:
            url_results = await asyncio.gather(
                *[self._fetch_proxy_list(proxy.address) for proxy in url_proxies],
                return_exceptions=True
            )

            for result in url_results:
                if isinstance(result, list):
                    proxy_list.extend(result)
                elif isinstance(result, Exception):
                    print(f"[LOG] 프록시 URL 처리 실패: {result}")

        return proxy_list

    async def get_next_available_proxy(self, db: Session, download_id: int = None) -> str:
        """Get the next available proxy"""
        try:
            proxy_list = await self.get_user_proxy_list(db)
            if not proxy_list:
                return None

            # Query already-failed proxies (those with success == False)
            failed_proxies = db.query(ProxyStatus).filter(
                ProxyStatus.success == False
            ).all()
            failed_proxy_addresses = {f"{p.ip}:{p.port}" for p in failed_proxies}

            print(f"[DEBUG] 전체 프록시: {len(proxy_list)}, 실패한 프록시: {len(failed_proxy_addresses)}")

            # Filter to only proxies that have not failed
            available_proxies = [proxy for proxy in proxy_list if proxy not in failed_proxy_addresses]

            if not available_proxies:
                print(f"[WARNING] 사용 가능한 프록시가 없음. 전체: {len(proxy_list)}, 실패: {len(failed_proxy_addresses)}")
                return None

            # Use a lock to protect concurrent access
            async with self._proxy_lock:
                # Sequential proxy selection based on download ID
                if download_id is not None:
                    # Per-download proxy index management
                    if download_id not in self.download_proxy_index:
                        # Spread the initial index based on current time (avoid collisions)
                        self.download_proxy_index[download_id] = (download_id + int(time.time())) % len(available_proxies)

                    # If the current index exceeds the number of available proxies, start over
                    if self.download_proxy_index[download_id] >= len(available_proxies):
                        self.download_proxy_index[download_id] = 0

                    selected_proxy = available_proxies[self.download_proxy_index[download_id]]
                    print(f"[LOG] 프록시 선택 (다운로드 {download_id}): {selected_proxy} (인덱스: {self.download_proxy_index[download_id]}/{len(available_proxies)})")
                    self.download_proxy_index[download_id] += 1
                else:
                    # Legacy sequential selection (kept for compatibility)
                    if self.current_proxy_index >= len(available_proxies):
                        self.current_proxy_index = 0

                    selected_proxy = available_proxies[self.current_proxy_index]
                    print(f"[LOG] 프록시 선택: {selected_proxy} (인덱스: {self.current_proxy_index}/{len(available_proxies)})")
                    self.current_proxy_index += 1
            return selected_proxy
        except Exception as e:
            print(f"[ERROR] get_next_available_proxy 실패: {e}")
            return None

    async def mark_proxy_failed(self, db: Session, proxy_addr: str):
        """Record a proxy failure"""
        try:
            # Split IP:Port
            if ':' in proxy_addr:
                ip, port = proxy_addr.split(':', 1)
                port = int(port) if port.isdigit() else None
            else:
                ip, port = proxy_addr, None

            print(f"[DEBUG] 프록시 파싱: {proxy_addr} -> IP: {ip}, Port: {port}")

            # Check whether an existing record is present
            existing = db.query(ProxyStatus).filter(
                ProxyStatus.ip == ip,
                ProxyStatus.port == port
            ).first()

            if existing:
                existing.success = False
                existing.last_used_at = datetime.datetime.now()
                print(f"[LOG] 프록시 실패 업데이트: {proxy_addr}")
            else:
                proxy_status = ProxyStatus(
                    ip=ip,
                    port=port,
                    success=False,
                    last_used_at=datetime.datetime.now()
                )
                db.add(proxy_status)
                print(f"[LOG] 프록시 실패 새로 기록: {proxy_addr}")

            db.commit()

            # Increment the failure count
            self.failed_count += 1

            # Print the total number of failed proxies after the failure
            print(f"[LOG] 현재 실패한 프록시 총 개수: {self.failed_count}")
        except Exception as e:
            print(f"[ERROR] mark_proxy_failed 실패: {e}")

    async def get_total_failed_count(self, db: Session) -> int:
        """Return the total number of failed proxies (queried from the DB)"""
        try:
            return db.query(ProxyStatus).filter(ProxyStatus.success == False).count()
        except Exception as e:
            print(f"[ERROR] get_total_failed_count 실패: {e}")
            return 0

    async def _fetch_proxy_list(self, url: str) -> List[str]:
        """Fetch a proxy list from a URL asynchronously"""
        cache_key = url
        current_time = time.time()

        # Check the cache
        if (cache_key in self.proxy_cache and
            current_time - self.proxy_cache[cache_key][1] < self.cache_timeout):
            cached_proxies = self.proxy_cache[cache_key][0]
            print(f"[LOG] 프록시 목록 캐시 사용: {len(cached_proxies)}개 - {url}")
            return cached_proxies

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        text = await response.text()
                        lines = text.strip().split('\n')
                        proxies = []

                        for line in lines:
                            line = line.strip()
                            if line and ':' in line:
                                # Check whether it is in IP:PORT form
                                if self._detect_proxy_type(line) == "single":
                                    proxies.append(line)

                        # Store in the cache
                        self.proxy_cache[cache_key] = (proxies, current_time)
                        print(f"[LOG] 프록시 목록 URL에서 {len(proxies)}개 프록시 로드: {url}")
                        return proxies
                    else:
                        print(f"[LOG] 프록시 목록 URL 접근 실패: {url} ({response.status})")
                        return []

        except Exception as e:
            print(f"[LOG] 프록시 목록 URL 처리 실패: {url} -> {e}")
            return []

    def _detect_proxy_type(self, address: str) -> str:
        """Detect the form of a proxy address"""
        if address.startswith(('http://', 'https://')):
            return "list"

        ip_port_pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$'
        if re.match(ip_port_pattern, address):
            return "single"

def detect_proxy_type(address: str) -> str:
    """Detect the form of a proxy address (public function)"""
    if address.startswith(('http://', 'https://')):
        return "list"

    ip_port_pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$'
    if re.match(ip_port_pattern, address):
        return "single"

        domain_port_pattern = r'^[a-zA-Z0-9.-]+:\d+$'
        if re.match(domain_port_pattern, address):
            return "single"

        return "list"

    async def test_proxy_async(self, proxy_addr: str, timeout: int = 15, lenient_mode: bool = False) -> bool:
        """Asynchronous proxy test"""

        if lenient_mode:
            return await self._test_proxy_simple(proxy_addr, timeout)
        else:
            return await self._test_proxy_https(proxy_addr, timeout)

    async def _test_proxy_simple(self, proxy_addr: str, timeout: int) -> bool:
        """Simple proxy connection test"""
        try:
            proxy_url = f"http://{proxy_addr}"
            timeout_config = aiohttp.ClientTimeout(total=timeout)

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            async with aiohttp.ClientSession(timeout=timeout_config) as session:
                async with session.get(
                    "http://httpbin.org/ip",
                    proxy=proxy_url,
                    headers=headers
                ) as response:
                    if response.status == 200:
                        text = await response.text()
                        if 'origin' in text:
                            print(f"[LOG] ✅ 간단 연결 테스트 성공: {proxy_addr}")
                            return True

                    print(f"[LOG] ❌ 간단 연결 테스트 실패: {proxy_addr} (상태: {response.status})")
                    return False

        except Exception as e:
            print(f"[LOG] ❌ 간단 연결 테스트 오류: {proxy_addr} ({str(e)[:100]})")
            return False

    async def _test_proxy_https(self, proxy_addr: str, timeout: int) -> bool:
        """HTTPS tunnel proxy test"""
        try:
            proxy_url = f"http://{proxy_addr}"
            timeout_config = aiohttp.ClientTimeout(total=timeout)

            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            ]

            headers = {
                'User-Agent': random.choice(user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'DNT': '1'
            }

            # Disable SSL verification
            connector = aiohttp.TCPConnector(ssl=False)

            async with aiohttp.ClientSession(
                timeout=timeout_config,
                connector=connector
            ) as session:
                async with session.get(
                    "https://1fichier.com/",
                    proxy=proxy_url,
                    headers=headers
                ) as response:
                    success_codes = [200, 301, 302, 403, 429, 404, 503]
                    if response.status in success_codes:
                        text = await response.text()
                        if len(text) > 100:
                            print(f"[LOG] ✅ HTTPS 터널 작동: {proxy_addr}")
                            return True
                        else:
                            print(f"[LOG] ❌ 터널 실패: {proxy_addr} (응답 내용 없음)")
                            return False
                    else:
                        print(f"[LOG] ❌ 터널 실패: {proxy_addr} (응답 코드: {response.status})")
                        return False

        except aiohttp.ClientProxyConnectionError:
            print(f"[LOG] ❌ 프록시 연결 불가: {proxy_addr}")
            return False
        except asyncio.TimeoutError:
            print(f"[LOG] ❌ 프록시 타임아웃: {proxy_addr}")
            return False
        except Exception as e:
            error_msg = str(e)
            if "Tunnel connection failed" in error_msg or "400 Bad Request" in error_msg:
                print(f"[LOG] ❌ HTTPS 터널 실패: {proxy_addr}")
            else:
                print(f"[LOG] ❌ 터널 테스트 오류: {proxy_addr} ({str(e)[:100]})")
            return False

    async def test_proxy_batch_async(
        self,
        db: Session,
        batch_proxies: List[str],
        req=None,
        lenient_mode: bool = False,
        max_concurrent: int = 10
    ) -> Tuple[List[str], List[str]]:
        """Asynchronous batch proxy test"""

        if not batch_proxies:
            print(f"[LOG] 테스트할 프록시가 없음")
            return [], []

        mode_text = " (관대한 모드)" if lenient_mode else ""
        print(f"[LOG] {len(batch_proxies)}개 프록시 비동기 배치 테스트 시작{mode_text}")

        # Check the request status
        if req:
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 프록시 테스트 중 정지됨: {req.id}")
                return [], []

        working_proxies = []
        failed_proxies = []

        # Limit concurrency with a semaphore
        semaphore = asyncio.Semaphore(max_concurrent)

        async def test_single_proxy_with_delay(proxy_addr: str) -> Tuple[str, bool]:
            async with semaphore:
                # Random delay to avoid back-to-back requests
                delay = random.uniform(0.2, 0.8)  # shorter delay since this is async
                await asyncio.sleep(delay)

                try:
                    result = await self.test_proxy_async(proxy_addr, timeout=10, lenient_mode=lenient_mode)
                    return proxy_addr, result
                except Exception as e:
                    print(f"[LOG] 프록시 {proxy_addr} 테스트 중 오류: {e}")
                    return proxy_addr, False

        # Test all proxies asynchronously
        tasks = [test_single_proxy_with_delay(proxy) for proxy in batch_proxies]

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, tuple):
                    proxy_addr, is_working = result
                    if is_working:
                        working_proxies.append(proxy_addr)
                        print(f"[LOG] ✅ 작동 프록시: {proxy_addr}")
                    else:
                        failed_proxies.append(proxy_addr)
                        print(f"[LOG] ❌ 실패 프록시: {proxy_addr}")
                elif isinstance(result, Exception):
                    print(f"[LOG] 프록시 테스트 예외: {result}")

        except Exception as e:
            print(f"[LOG] 배치 테스트 중 오류: {e}")

        print(f"[LOG] 비동기 배치 테스트 완료: 성공 {len(working_proxies)}개, 실패 {len(failed_proxies)}개")
        return working_proxies, failed_proxies

    async def get_working_proxy_async(
        self,
        db: Session,
        max_test: int = 15,
        req=None,
        lenient_mode: bool = False
    ) -> Optional[str]:
        """Find a working proxy asynchronously"""

        # Get the list of unused proxies
        user_proxy_list = await self.get_user_proxy_list(db)

        # Proxy addresses already used
        used_proxies = db.query(ProxyStatus).filter(
            ProxyStatus.ip.isnot(None),
            ProxyStatus.port.isnot(None)
        ).all()
        used_proxy_addresses = {f"{p.ip}:{p.port}" for p in used_proxies}

        # Filter to unused proxies
        unused_proxies = [p for p in user_proxy_list if p not in used_proxy_addresses]

        if not unused_proxies:
            print(f"[LOG] 사용 가능한 프록시가 없음")
            return None

        # Place successful proxies first by priority
        successful_proxies = db.query(ProxyStatus).filter(
            ProxyStatus.last_status == 'success'
        ).all()
        priority_proxies = [f"{p.ip}:{p.port}" for p in successful_proxies if f"{p.ip}:{p.port}" in unused_proxies]
        other_proxies = [p for p in unused_proxies if p not in priority_proxies]

        # Place priority proxies at the front
        final_proxies = priority_proxies + other_proxies
        batch_proxies = final_proxies[:max_test]

        print(f"[LOG] 전체 프록시: {len(user_proxy_list)}개, 미사용 프록시: {len(unused_proxies)}개")
        print(f"[LOG] 우선순위 프록시: {len(priority_proxies)}개")

        # Asynchronous batch test
        working_proxies, failed_proxies = await self.test_proxy_batch_async(
            db, batch_proxies, req, lenient_mode
        )

        # Record the failed proxies in the DB
        for failed_proxy in failed_proxies:
            self.mark_proxy_used(db, failed_proxy, success=False)

        return working_proxies[0] if working_proxies else None

    def mark_proxy_used(self, db: Session, proxy_addr: str, success: bool):
        """Record the proxy usage result in the DB (kept synchronous)"""
        try:
            if ':' not in proxy_addr:
                print(f"[LOG] 잘못된 프록시 주소 형식: {proxy_addr}")
                return

            ip, port = proxy_addr.strip().split(':', 1)

            # Check for an existing record
            existing = db.query(ProxyStatus).filter(
                ProxyStatus.ip == ip,
                ProxyStatus.port == int(port)
            ).first()

            current_time = datetime.datetime.now()

            if existing:
                # Update the existing record
                existing.last_status = 'success' if success else 'fail'
                existing.success = success
                existing.last_used_at = current_time
                if not success:
                    existing.last_failed_at = current_time
            else:
                # Create a new record
                new_record = ProxyStatus(
                    ip=ip,
                    port=int(port),
                    last_status='success' if success else 'fail',
                    success=success,
                    last_used_at=current_time,
                    last_failed_at=current_time if not success else None
                )
                db.add(new_record)

            db.commit()

        except Exception as e:
            print(f"[LOG] 프록시 사용 기록 실패 ({proxy_addr}): {e}")
            db.rollback()


# Global instance
proxy_manager = ProxyManager()