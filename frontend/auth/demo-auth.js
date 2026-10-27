// ─────────────────────────────────────────────────────────────
//  데모 로그인 스위치 — 구글 팝업 없이 앱을 돌려보기 위한 셔틀.
//
//  평소: 진짜 Firebase 구현(auth/signInWithPopup/...)을 그대로 통과시킨다.
//  데모: 가짜 데모 계정으로 즉시 로그인되고, getIdToken()이 "fake:..." 토큰을
//        반환한다 → 백엔드 FIREBASE_MODE=fake 가 이를 받아 진짜 JWT를 발급.
//
//  ⚠️ 데모 로그인이 실제로 통하려면 백엔드 .env 가 FIREBASE_MODE=fake 여야 한다.
//     (google 모드면 교환 단계에서 401 — 프론트만 데모여도 백엔드는 안 속는다.
//      fake 모드는 인증이 무력화되므로 절대 공개 배포에서 켜지 말 것.)
// ─────────────────────────────────────────────────────────────
import { auth as realAuth, provider } from "../firebase-config.js";
import {
  signInWithPopup as realSignInWithPopup,
  onAuthStateChanged as realOnAuthStateChanged,
  signOut as realSignOut,
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

// 기본은 구글 로그인. ?demo=1 을 붙이면 이 탭(세션) 동안 데모 로그인, ?demo=0 이면 해제.
// (2026-07-29~10-13 에는 임시로 데모가 기본값이었다 — 서버를 FIREBASE_MODE=google 로 바꾸면
//  프론트가 가짜 토큰을 보내 전원 401 이 되는 문제가 있어 옵트인으로 되돌렸다.)
const DEMO_FLAG_KEY = "glitch_demo_on";
const q = new URLSearchParams(location.search).get("demo");
sessionStorage.removeItem("glitch_demo_off"); // 예전(기본 ON 시절) 해제 플래그 — 더는 쓰지 않는다
if (q === "1") sessionStorage.setItem(DEMO_FLAG_KEY, "1");
if (q === "0") sessionStorage.removeItem(DEMO_FLAG_KEY);
export const DEMO = sessionStorage.getItem(DEMO_FLAG_KEY) === "1";

// ── 데모 구현 (Firebase Auth의 겉모습만 흉내) ──
// 시드 계정 cho@example.com 으로 로그인해야 데모 프로젝트가 보인다.
const demoUser = {
  uid: "demo-user",
  email: "cho@example.com",
  displayName: "Cho Euna",
  getIdToken: async () => "fake:cho@example.com:Cho Euna",
};
const demoAuth = { currentUser: null };
const listeners = new Set();
function fire() {
  listeners.forEach((cb) => {
    try {
      cb(demoAuth.currentUser);
    } catch (e) {
      console.error(e);
    }
  });
}

async function demoSignInWithPopup() {
  demoAuth.currentUser = demoUser;
  fire();
  return { user: demoUser };
}
function demoOnAuthStateChanged(_auth, cb) {
  listeners.add(cb);
  queueMicrotask(() => cb(demoAuth.currentUser)); // 실제 SDK처럼 비동기 첫 통지
  return () => listeners.delete(cb);
}
async function demoSignOut() {
  demoAuth.currentUser = null;
  fire();
}

if (DEMO) console.warn("[auth] 데모 로그인 모드 — 구글 인증을 우회합니다 (?demo=0 으로 해제)");

// ── 내보내기: 데모면 가짜, 아니면 진짜 ──
export const auth = DEMO ? demoAuth : realAuth;
export { provider };
export const signInWithPopup = DEMO ? demoSignInWithPopup : realSignInWithPopup;
export const onAuthStateChanged = DEMO ? demoOnAuthStateChanged : realOnAuthStateChanged;
export const signOut = DEMO ? demoSignOut : realSignOut;
