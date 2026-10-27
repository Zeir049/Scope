// Firebase 초기화 파일
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.12.0/firebase-app.js";
import {
  getAuth,
  GoogleAuthProvider,
  setPersistence,
  browserSessionPersistence,
} from "https://www.gstatic.com/firebasejs/10.12.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyDHDfDQ8G0nAa37QSgjdUtVyWmlQyL0a00",
  authDomain: "test-project-825b6.firebaseapp.com",
  projectId: "test-project-825b6",
  storageBucket: "test-project-825b6.firebasestorage.app",
  messagingSenderId: "685997486673",
  appId: "1:685997486673:web:d0a1435094aa210481be70",
  measurementId: "G-RMNZXPVVNE"
};

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

// 기본값(local persistence)은 브라우저를 완전히 껐다 켜도 로그인이 유지됩니다.
// "탭/창을 닫으면 로그아웃" 요구사항에 맞게, 이 탭이 열려있는 동안에만
// 로그인이 유지되는 session persistence로 변경합니다.
setPersistence(auth, browserSessionPersistence);

export const provider = new GoogleAuthProvider();

// signOut() 이후에도 브라우저에 남아있는 구글 세션으로 인해
// 로그인 창이 안 뜨고 바로 자동 로그인되는 것을 막기 위해,
// 매번 계정 선택 화면을 강제로 띄웁니다.
provider.setCustomParameters({ prompt: "select_account" });
