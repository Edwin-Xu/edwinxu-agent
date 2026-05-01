"use client";

import Link from "next/link";
import React from "react";
import { useTheme } from "../theme";

export default function SettingsPage() {
  const { preference, setPreference, resolved } = useTheme();

  return (
    <div className="layout" style={{ gridTemplateColumns: "1fr", maxWidth: 820, margin: "0 auto" }}>
      <div className="panel">
        <div className="panelHeader">
          <div style={{ fontWeight: 700 }}>设置</div>
          <Link className="btn" href="/">
            返回
          </Link>
        </div>
        <div className="panelBody">
          <div style={{ fontWeight: 700, marginBottom: 8 }}>主题</div>
          <div className="muted small" style={{ marginBottom: 10 }}>
            当前主题：{resolved === "light" ? "浅色" : "深色"}
          </div>
          <select className="input" value={preference} onChange={(e) => setPreference(e.target.value as any)}>
            <option value="light">浅色</option>
            <option value="dark">深色</option>
            <option value="system">跟随系统</option>
          </select>
        </div>
      </div>
    </div>
  );
}

