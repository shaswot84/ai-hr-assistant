"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";

export interface GenUIWidgetData {
  type: string;
  spec?: string;
  ui_type?: "comparison" | "calculator" | "procedure" | "custom" | string;
  title?: string;
  html: string;
  [key: string]: any;
}

export interface GenUIIframeWidgetProps {
  widget: GenUIWidgetData;
  onAction?: (actionText: string) => void;
  disabled?: boolean;
}

export function GenUIIframeWidget({ widget, onAction, disabled = false }: GenUIIframeWidgetProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const fullscreenIframeRef = useRef<HTMLIFrameElement | null>(null);
  const [height, setHeight] = useState<number>(200);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [renderKey, setRenderKey] = useState<number>(0);
  const [copied, setCopied] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const instanceId = useRef(`genui_${Math.random().toString(36).substring(2, 9)}`);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      if (!event.data || typeof event.data !== "object") return;

      const { type, height: reportedHeight, text } = event.data;

      if (type === "ag_ui:resize" && typeof reportedHeight === "number") {
        const clamped = Math.max(60, Math.min(reportedHeight, 700));
        setHeight(clamped);
        setIsLoading(false);
      } else if (type === "ag_ui:action" && typeof text === "string") {
        if (!disabled && onAction) {
          onAction(text);
          if (isFullscreen) {
            setIsFullscreen(false);
          }
        }
      }
    },
    [disabled, onAction, isFullscreen]
  );

  useEffect(() => {
    window.addEventListener("message", handleMessage);
    return () => {
      window.removeEventListener("message", handleMessage);
    };
  }, [handleMessage]);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && isFullscreen) {
        setIsFullscreen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen]);

  const handleReset = () => {
    setRenderKey((k) => k + 1);
    setIsLoading(true);
  };

  const handleCopyCode = async () => {
    if (!widget.html) return;
    try {
      await navigator.clipboard.writeText(widget.html);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy code", err);
    }
  };

  const isStreaming = widget.status === "streaming";

  const getPillLabel = () => {
    if (isStreaming) {
      return {
        label: "⚡ Generating Interactive UI...",
        color: "bg-blue-50 text-blue-700 border-blue-200 animate-pulse",
      };
    }
    switch (widget.ui_type) {
      case "calculator":
        return { label: "Interactive Calculator", color: "bg-indigo-50 text-indigo-700 border-indigo-200" };
      case "procedure":
        return { label: "Interactive Checklist", color: "bg-emerald-50 text-emerald-700 border-emerald-200" };
      case "comparison":
        return { label: "Policy Matrix", color: "bg-blue-50 text-blue-700 border-blue-200" };
      default:
        return { label: "AG-UI Artifact", color: "bg-purple-50 text-purple-700 border-purple-200" };
    }
  };

  const pill = getPillLabel();

  return (
    <div className="mt-2.5 w-full max-w-full">
      {/* Outer Card Container */}
      <div className="overflow-hidden rounded-xl border border-zinc-200/90 bg-white shadow-2xs transition-all hover:border-zinc-300">
        {/* Header / Toolbar */}
        <div className="flex items-center justify-between border-b border-zinc-100 bg-zinc-50/70 px-3 py-1.5 text-xs">
          <div className="flex items-center gap-2">
            <span className="flex h-4.5 w-4.5 items-center justify-center rounded-md bg-gradient-to-tr from-blue-600 to-indigo-600 text-white shadow-2xs">
              <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2.5}
                  d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
                />
              </svg>
            </span>
            <span className="font-semibold text-zinc-800 truncate max-w-[180px] sm:max-w-xs">
              {widget.title || "Interactive GenUI Component"}
            </span>
            <span className={`hidden sm:inline-flex rounded-full px-1.5 py-0.5 text-[9px] font-semibold border ${pill.color}`}>
              {pill.label}
            </span>
          </div>

          <div className="flex items-center gap-0.5">
            {/* Copy Button */}
            <button
              type="button"
              onClick={handleCopyCode}
              title="Copy HTML content"
              className="rounded p-1 text-zinc-400 hover:bg-zinc-200/70 hover:text-zinc-700 transition-colors"
            >
              {copied ? (
                <svg className="h-3.5 w-3.5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                </svg>
              ) : (
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                  />
                </svg>
              )}
            </button>

            {/* Reset Button */}
            <button
              type="button"
              onClick={handleReset}
              title="Reset component state"
              className="rounded p-1 text-zinc-400 hover:bg-zinc-200/70 hover:text-zinc-700 transition-colors"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                />
              </svg>
            </button>

            {/* Fullscreen Expansion Button */}
            <button
              type="button"
              onClick={() => setIsFullscreen(true)}
              title="Expand to Fullscreen"
              className="rounded p-1 text-zinc-400 hover:bg-zinc-200/70 hover:text-zinc-700 transition-colors"
            >
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"
                />
              </svg>
            </button>
          </div>
        </div>

        {/* Sandboxed Iframe Container */}
        <div className="relative w-full bg-white transition-[height] duration-150 ease-out">
          <iframe
            key={renderKey}
            id={instanceId.current}
            ref={iframeRef}
            srcDoc={widget.html}
            sandbox="allow-scripts"
            title={widget.title || "AG-UI Generative Interface"}
            onLoad={() => setIsLoading(false)}
            className="w-full border-0 bg-transparent p-0 m-0"
            style={{
              height: `${height}px`,
              display: "block",
              overflow: "hidden",
            }}
          />
        </div>

        {/* Bottom Status Bar */}
        <div className="flex items-center justify-between border-t border-zinc-100 bg-zinc-50/40 px-2.5 py-1 text-[9px] text-zinc-400">
          {isStreaming ? (
            <div className="flex items-center gap-1 text-blue-600 font-medium">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-600 animate-ping" />
              <span>Streaming component structure…</span>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              <span>AG-UI Sandbox</span>
            </div>
          )}
          <span>{isStreaming ? "Progressive Hydration" : "Interactive"}</span>
        </div>
      </div>

      {/* Fullscreen Modal Dialog */}
      {isFullscreen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs animate-fadeIn">
          <div className="relative flex h-[85vh] w-full max-w-3xl flex-col rounded-2xl bg-white shadow-2xl overflow-hidden border border-zinc-200">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-zinc-200 bg-zinc-50 px-4 py-3">
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-md bg-blue-600 text-white">
                  <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2.5}
                      d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
                    />
                  </svg>
                </span>
                <div>
                  <h3 className="text-xs font-bold text-zinc-900">{widget.title || "Interactive GenUI Component"}</h3>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleReset}
                  className="rounded-lg border border-zinc-300 bg-white px-2 py-1 text-xs font-medium text-zinc-700 hover:bg-zinc-50 transition-colors"
                >
                  Reset
                </button>
                <button
                  type="button"
                  onClick={() => setIsFullscreen(false)}
                  className="rounded-lg bg-zinc-900 px-2.5 py-1 text-xs font-semibold text-white hover:bg-zinc-800 transition-colors"
                >
                  Close
                </button>
              </div>
            </div>

            {/* Modal Body Iframe */}
            <div className="flex-1 w-full bg-zinc-50 p-2 overflow-auto">
              <iframe
                ref={fullscreenIframeRef}
                srcDoc={widget.html}
                sandbox="allow-scripts"
                title="Fullscreen GenUI view"
                className="h-full w-full rounded-xl border border-zinc-200 bg-white shadow-xs"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
