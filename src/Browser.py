import sys

from AssertCondition import AssertCondition
from Exceptions.NoAccessTokenException import NoAccessTokenException
from Exceptions.RateLimitException import RateLimitException
from Exceptions.InvalidIMAPCredentialsException import InvalidIMAPCredentialsException
from Exceptions.Fail2FAException import Fail2FAException
from Exceptions.FailFind2FAException import FailFind2FAException
from Match import Match
import httpx
from pprint import pprint
from bs4 import BeautifulSoup
from datetime import datetime
import threading
from time import sleep, time
from Config import Config
from Exceptions.StatusCodeAssertException import StatusCodeAssertException
import pickle
from pathlib import Path
import jwt
from IMAP import IMAP # Added to automate 2FA
import imaplib2
import random

from SharedData import SharedData


class Browser:
    SESSION_REFRESH_INTERVAL = 1800.0
    STREAM_WATCH_INTERVAL = 120.0

    def __init__(self, log, stats, config: Config, account: str, sharedData: SharedData):
        """
        Initialize the Browser class

        :param log: log variable
        :param config: Config class object
        :param account: account string
        """
        self.client = httpx.Client(
            http2=True,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=30.0,
        )

        self.log = log
        self.stats = stats
        self.config = config
        self.currentlyWatching = {}
        self.account = account
        self.sharedData = sharedData
        self.ref = "Referer"

    def _request_with_retry(self, method, url, max_retries=3, **kwargs):
        """
        Send an HTTP request with exponential backoff retry on 429/5xx errors.

        :param method: HTTP method string ("GET", "POST", "PUT")
        :param url: request URL
        :param max_retries: max retry attempts
        :param kwargs: additional args passed to httpx.Client.request()
        :return: httpx.Response
        """
        for attempt in range(max_retries + 1):
            res = self.client.request(method, url, **kwargs)
            if res.status_code == 429:
                retry_after = int(res.headers.get("Retry-After", 5))
                jitter = random.uniform(0.5, 2.0)
                wait = retry_after + jitter
                self.log.warning(f"Rate limited on {url}. Retrying in {wait:.1f}s (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries:
                    sleep(wait)
                    continue
                raise RateLimitException(retry_after)
            if res.status_code >= 500 and attempt < max_retries:
                wait = (2 ** attempt) + random.uniform(0.5, 1.5)
                self.log.warning(f"Server error {res.status_code} on {url}. Retrying in {wait:.1f}s")
                sleep(wait)
                continue
            return res
        return res

    def _safe_json(self, res, context=""):
        """
        Safely parse JSON from a response, with logging on failure.

        :param res: httpx.Response
        :param context: description of what the request was for (for logging)
        :return: parsed JSON dict/list, or None on failure
        """
        if res.status_code < 200 or res.status_code >= 300:
            self.log.warning(f"{context}: unexpected status {res.status_code}")
            return None
        content_type = res.headers.get("content-type", "")
        if "json" not in content_type and "javascript" not in content_type:
            self.log.warning(f"{context}: unexpected content-type '{content_type}'")
            return None
        try:
            return res.json()
        except Exception as e:
            self.log.error(f"{context}: failed to parse JSON - {e}")
            return None

    def login(self, username: str, password: str, imapusername: str, imappassword: str, imapserver: str, refreshLock) -> bool:
        """
        Login to the website using given credentials. Obtain necessary tokens.

        :param username: string, username of the account
        :param password: string, password of the account
        :return: boolean, login successful or not
        """
        # Get necessary cookies from the main page
        self.client.get(
            "https://login.leagueoflegends.com/?redirect_uri=https://lolesports.com/&lang=en")
        self.__loadCookies()
        try:
            refreshLock.acquire()

            # Step 1: Initialize auth session (POST) — must NOT include prompt=none
            # as that skips session creation and returns interaction_required immediately
            initData = {
                "client_id": "esports-rna-prod",
                "redirect_uri": "https://account.rewards.lolesports.com/v1/session/oauth-callback",
                "response_type": "code",
                "scope": "openid",
            }
            initRes = self._request_with_retry(
                "POST", "https://auth.riotgames.com/api/v1/authorization", json=initData)
            if initRes.status_code != 200:
                self.log.error(f"Auth init failed with status {initRes.status_code}")
                return False

            # Step 2: Submit credentials (PUT)
            data = {"type": "auth", "username": username,
                    "password": password, "remember": True, "language": "en_US"}
            res = self._request_with_retry(
                "PUT", "https://auth.riotgames.com/api/v1/authorization", json=data)
            if res.status_code == 429:
                retryAfter = res.headers.get('Retry-After', '60')
                raise RateLimitException(retryAfter)

            resJson = self._safe_json(res, "login PUT")
            if resJson is None:
                return False

            if "error" in resJson:
                self.log.error(f"Auth error: {resJson['error']}")
                return False

            if "multifactor" in resJson.get("type", ""):
                if (imapserver != ""):
                    refreshLock.release()
                    #Handles all IMAP requests
                    req = self.IMAPHook(imapusername, imappassword, imapserver)

                    self.stats.updateStatus(self.account, f"[green]FETCHED 2FA CODE")

                    data = {"type": "multifactor", "code": req.code, "rememberDevice": True}
                    res = self._request_with_retry(
                        "PUT", "https://auth.riotgames.com/api/v1/authorization", json=data)
                    resJson = self._safe_json(res, "login 2FA")
                    if resJson is None:
                        return False
                    if 'error' in resJson:
                        if resJson['error'] == 'multifactor_attempt_failed':
                            raise Fail2FAException

                else:
                    twoFactorCode = input(f"Enter 2FA code for {self.account}:\n")
                    self.stats.updateStatus(self.account, f"[green]CODE SENT")
                    data = {"type": "multifactor", "code": twoFactorCode, "rememberDevice": True}
                    res = self._request_with_retry(
                        "PUT", "https://auth.riotgames.com/api/v1/authorization", json=data)
                    resJson = self._safe_json(res, "login 2FA manual")
                    if resJson is None:
                        return False

            # Finish OAuth2 login
            if "response" not in resJson or "parameters" not in resJson.get("response", {}):
                self.log.error(f"Auth response missing expected fields: {list(resJson.keys())}")
                return False
            res = self.client.get(resJson["response"]["parameters"]["uri"])
        except KeyError:
            return False
        except RateLimitException as ex:
            self.log.error(f"You are being rate-limited. Retry after {ex}")
            return False
        finally:
            if refreshLock.locked():
                refreshLock.release()
        # Login to lolesports.com, riotgames.com, and playvalorant.com
        token, state = self.__getLoginTokens(res.text)
        if token and state:
            data = {"token": token, "state": state}
            self.client.post(
                "https://login.riotgames.com/sso/login", data=data)
            self.client.post(
                "https://login.lolesports.com/sso/login", data=data)
            self.client.post(
                "https://login.playvalorant.com/sso/login", data=data)
            self.client.post(
                "https://login.leagueoflegends.com/sso/callback", data=data)
            self.client.get(
                "https://auth.riotgames.com/authorize?client_id=esports-rna-prod&redirect_uri=https://account.rewards.lolesports.com/v1/session/oauth-callback&response_type=code&scope=openid&prompt=none&state=https://lolesports.com/?memento=na.en_GB")


            resAccessToken = self._request_with_retry(
                "GET", "https://account.rewards.lolesports.com/v1/session/token",
                headers={"Origin": "https://lolesports.com", self.ref: "https://lolesports.com"})

            if resAccessToken.status_code != 200:
                if self.ref == "Referer":
                    self.ref = "Referrer"
                else:
                    self.ref = "Referer"
                resAccessToken = self._request_with_retry(
                    "GET", "https://account.rewards.lolesports.com/v1/session/token",
                    headers={"Origin": "https://lolesports.com", self.ref: "https://lolesports.com"})

            self._request_with_retry(
                "GET", "https://account.rewards.lolesports.com/v1/session/clientconfig/rms",
                headers={"Origin": "https://lolesports.com", self.ref: "https://lolesports.com"})
            if resAccessToken.status_code == 200:
                self.__dumpCookies()
                return True
        return False

    def IMAPHook(self, usern, passw, server):
        try:
            M = imaplib2.IMAP4_SSL(server)
            M.login(usern, passw)
            M.select("INBOX")
            idler = IMAP(M)
            idler.start()
            idler.join()
            M.logout()
            return idler
        except FailFind2FAException:
            self.log.error(f"Failed to find 2FA code for {self.account}")
        except:
            raise InvalidIMAPCredentialsException()

    def refreshSession(self):
        """
        Refresh access and entitlement tokens
        """
        try:
            headers = {"Origin": "https://lolesports.com"}
            resAccessToken = self._request_with_retry(
                "GET", "https://account.rewards.lolesports.com/v1/session/refresh", headers=headers)
            AssertCondition.statusCodeMatches(200, resAccessToken)
            self.__dumpCookies()
        except StatusCodeAssertException as ex:
            self.log.error("Failed to refresh session")
            self.log.error(ex)
            raise ex

    def maintainSession(self):
        """
        Periodically maintain the session by refreshing the access_token
        """
        if self.__needSessionRefresh():
            self.log.debug("Refreshing session.")
            self.refreshSession()

    def sendWatchToLive(self) -> list:
        """
        Send watch event for all the live matches
        """
        watchFailed = []
        for tid in self.sharedData.getLiveMatches():
            try:
                self.__sendWatch(self.sharedData.getLiveMatches()[tid])
            except StatusCodeAssertException as ex:
                self.log.error(f"Failed to send watch heartbeat for {self.sharedData.getLiveMatches()[tid].league}")
                self.log.error(ex)
                watchFailed.append(self.sharedData.getLiveMatches()[tid].league)
        return watchFailed

    def checkNewDrops(self, lastCheckTime = 0):
        try:
            headers = {"Origin": "https://lolesports.com",
                   "Authorization": "Cookie access_token"}
            res = self._request_with_retry(
                "GET", "https://account.service.lolesports.com/fandom-account/v1/earnedDrops?locale=en_GB&site=LOLESPORTS", headers=headers)
            resJson = self._safe_json(res, "checkNewDrops")
            if resJson is None:
                return [], 0
            return [drop for drop in resJson if lastCheckTime <= drop["unlockedDateMillis"]], len(resJson)
        except (KeyError, TypeError):
            self.log.debug("Drop check failed")
            return [], 0

    def __getAccessToken(self) -> str:
        """Get access_token from cookies, checking both browser and API cookie names."""
        cookies = dict(self.client.cookies)
        for key in ("access_token", "__Secure-access_token"):
            if key in cookies:
                return cookies[key]
        return None

    def __needSessionRefresh(self) -> bool:
        token = self.__getAccessToken()
        if token is None:
            raise NoAccessTokenException()

        res = jwt.decode(token, options={"verify_signature": False})
        timeLeft = res['exp'] - int(time())
        self.log.debug(f"{timeLeft}s until session expires.")
        if timeLeft < 600:
            return True
        return False

    def __sendWatch(self, match: Match):
        """
        Sends watch event for a match

        :param match: Match object
        :return: object, response of the request
        """
        data = {"stream_id": match.streamChannel,
                "source": match.streamSource,
                "stream_position_time": datetime.utcnow().isoformat(sep='T', timespec='milliseconds')+'Z',
                "geolocation": {"code": "CZ", "area": "EU"},
                "tournament_id": match.tournamentId}
        headers = {"Origin": "https://lolesports.com"}
        res = self._request_with_retry(
            "POST", "https://rex.rewards.lolesports.com/v1/events/watch", json=data, headers=headers)
        AssertCondition.statusCodeMatches(201, res)

    def __getLoginTokens(self, form: str) -> tuple[str, str]:
        """
        Extract token and state from login page html

        :param html: string, html of the login page
        :return: tuple, token and state
        """
        page = BeautifulSoup(form, features="html.parser")
        token = None
        state = None
        if tokenInput := page.find("input", {"name": "token"}):
            token = tokenInput.get("value", "")
        if tokenInput := page.find("input", {"name": "state"}):
            state = tokenInput.get("value", "")
        return token, state

    def hasValidSavedSession(self) -> bool:
        """
        Check if a saved session exists with an access_token that isn't expired.
        Used to skip browser login when cookies were obtained via browser_login.py.
        """
        if not self.__loadCookies():
            return False
        token = self.__getAccessToken()
        if token is None:
            return False
        try:
            res = jwt.decode(token, options={"verify_signature": False})
            timeLeft = res['exp'] - int(time())
            if timeLeft > 0:
                self.log.info(f"Loaded saved session for {self.account} ({timeLeft}s until expiry)")
                return True
            else:
                self.log.info(f"Saved session for {self.account} is expired, attempting refresh...")
                try:
                    self.refreshSession()
                    return True
                except Exception:
                    self.log.warning(f"Session refresh failed for {self.account}")
                    return False
        except Exception:
            return False

    def __dumpCookies(self):
        with open(f'./sessions/{self.account}.saved', 'wb') as f:
            pickle.dump(dict(self.client.cookies), f)

    def __loadCookies(self):
        if Path(f'./sessions/{self.account}.saved').exists():
            try:
                with open(f'./sessions/{self.account}.saved', 'rb') as f:
                    cookies = pickle.load(f)
                    if isinstance(cookies, dict):
                        # Browser cookies use __Secure- prefix; add unprefixed aliases
                        # so the server-side "Cookie access_token" auth header works
                        for key in list(cookies.keys()):
                            if key.startswith("__Secure-"):
                                alias = key[len("__Secure-"):]
                                if alias not in cookies:
                                    cookies[alias] = cookies[key]
                        self.client.cookies.update(cookies)
                    else:
                        # Old format (CookieJar from cloudscraper) — discard
                        self.log.debug("Discarding old cookie format, will re-login")
                        Path(f'./sessions/{self.account}.saved').unlink()
                        return False
                    return True
            except Exception:
                self.log.debug("Failed to load saved session, will re-login")
                Path(f'./sessions/{self.account}.saved').unlink(missing_ok=True)
                return False
        return False
