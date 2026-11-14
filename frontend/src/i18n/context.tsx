"use client";

import React, { createContext, useCallback, useContext, useEffect, useSyncExternalStore } from "react";
import enDict from "./en.json";
import trDict from "./tr.json";

export type Lang = "en" | "tr";

type Dict = typeof enDict;

const DICTS: Record<Lang, Dict> = {
  en: enDict,
  tr: trDict,
};

const STORAGE_KEY = "aeon_lang";
const LANG_EVENT = "aeon-lang-change";

interface BilingualField {
  tr?: string;
  en?: string;
}

interface I18nContextValue {
  lang: Lang;
  setLang: (next: Lang) => void;
  toggleLang: () => void;
  dict: Dict;
  bilingual: (field?: BilingualField | null) => string;
}

function subscribeLang(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(LANG_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(LANG_EVENT, callback);
  };
}

function getClientLang(): Lang {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved === "tr" || saved === "en") return saved;
  } catch {
    // Ignore storage errors
  }
  return "en";
}

function getServerLang(): Lang {
  return "en";
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const lang = useSyncExternalStore(subscribeLang, getClientLang, getServerLang);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
      window.dispatchEvent(new Event(LANG_EVENT));
    } catch {
      // Ignore storage errors
    }
  }, []);

  const toggleLang = useCallback(() => {
    setLang(lang === "en" ? "tr" : "en");
  }, [lang, setLang]);

  const bilingual = useCallback(
    (field?: BilingualField | null) => {
      if (!field) return "";
      return field[lang] ?? field.en ?? field.tr ?? "";
    },
    [lang]
  );

  return (
    <I18nContext.Provider
      value={{
        lang,
        setLang,
        toggleLang,
        dict: DICTS[lang],
        bilingual,
      }}
    >
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within an I18nProvider");
  }
  return ctx;
}
