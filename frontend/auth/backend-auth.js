// ─────────────────────────────────────────────────────────────
//  구글 로그인 ↔ 백엔드 JWT 교환.
//  Firebase(또는 데모) 로그인이 되면 ID 토큰을 POST /auth/firebase 로 보내
//  자체 JWT를 받아 sessionStorage 에 둔다(탭을 닫으면 사라짐).
//  api.js 에 토큰 공급자를 등록해, 401 이면 한 번 재교환 후 재시도한다.
// ─────────────────────────────────────────────────────────────
import { auth, onAuthStateChanged } from "./demo-auth.js"; // 데모 모드면 가짜, 아니면 진짜 Firebase
import { api, configureAuth } from "../api.js";

const TOKEN_KEY = "glitch_backend_token";

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY);
}
function setToken(token) {
  sessionStorage.setItem(TOKEN_KEY, token);
}
function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

let exchangePromise = null;
let authFailedHandler = null;

/** 재교환까지 실패했을 때(로그인 만료) 부를 콜백. script.js 가 로그인 화면으로 보낸다. */
export function onBackendAuthFailed(cb) {
  authFailedHandler = cb;
}

async function exchange(user) {
  const idToken = await user.getIdToken();
  const res = await api.firebaseLogin(idToken);
  setToken(res.access_token);
  console.log("[auth] 백엔드 로그인 완료:", res.user.email);
  return res.access_token;
}

function startExchange(user) {
  exchangePromise = exchange(user).catch((e) => {
    exchangePromise = null;
    throw e;
  });
  return exchangePromise;
}

onAuthStateChanged(auth, (user) => {
  if (user) {
    if (!getToken()) startExchange(user).catch((e) => console.error("[auth] 백엔드 토큰 교환 실패:", e));
  } else {
    clearToken();
    exchangePromise = null;
  }
});

/** 백엔드 JWT를 보장한다. 없으면 교환을 (재)시도하고, 못 구하면 던진다. */
export async function ensureBackendToken() {
  const t = getToken();
  if (t) return t;
  if (exchangePromise) return exchangePromise;
  if (auth.currentUser) return startExchange(auth.currentUser);
  throw new Error("로그인이 필요합니다. 다시 로그인해주세요.");
}

// 401 → 토큰을 버리고 한 번만 새로 교환한다. 동시에 여러 요청이 401 이어도 교환은 하나.
let refreshPromise = null;
async function refreshToken() {
  if (refreshPromise) return refreshPromise;
  if (!auth.currentUser) return null;
  clearToken();
  exchangePromise = null;
  refreshPromise = startExchange(auth.currentUser).finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

configureAuth({
  getToken,
  ensureToken: () => (auth.currentUser ? ensureBackendToken() : null),
  refresh: refreshToken,
  onAuthFailed: () => authFailedHandler?.(),
});
