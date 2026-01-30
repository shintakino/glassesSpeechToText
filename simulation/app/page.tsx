'use client';

import { useState } from 'react';
import AudioRecorder from './components/AudioRecorder';

export default function Home() {
    const [transcript, setTranscript] = useState('');
    const [status, setStatus] = useState<'disconnected' | 'connecting' | 'connected' | 'recording'>('disconnected');
    const [error, setError] = useState<string | null>(null);

    const handleTranscript = (text: string, isFinal: boolean) => {
        if (isFinal) {
            setTranscript((prev) => prev + (prev ? ' ' : '') + text + '.');
        }
    };

    const getStatusColor = () => {
        switch (status) {
            case 'disconnected': return 'bg-rose-500 shadow-rose-500/50';
            case 'connecting': return 'bg-amber-400 shadow-amber-400/50';
            case 'connected': return 'bg-emerald-400 shadow-emerald-400/50';
            case 'recording': return 'bg-rose-500 animate-pulse shadow-rose-500/50';
            default: return 'bg-slate-400';
        }
    };

    const getStatusText = () => {
        switch (status) {
            case 'disconnected': return 'Disconnected';
            case 'connecting': return 'Connecting...';
            case 'connected': return 'Ready';
            case 'recording': return 'Listening...';
            default: return 'Unknown';
        }
    };

    return (
        <main className="min-h-screen bg-slate-900 text-white font-sans selection:bg-indigo-500 selection:text-white overflow-hidden relative">

            {/* Dynamic Background */}
            <div className="absolute top-0 left-0 w-full h-full overflow-hidden z-0">
                <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-purple-600/30 rounded-full blur-[120px] animate-blob mix-blend-screen"></div>
                <div className="absolute top-[20%] right-[-10%] w-[40%] h-[60%] bg-blue-600/30 rounded-full blur-[120px] animate-blob animation-delay-2000 mix-blend-screen"></div>
                <div className="absolute bottom-[-10%] left-[20%] w-[60%] h-[40%] bg-indigo-600/30 rounded-full blur-[120px] animate-blob animation-delay-4000 mix-blend-screen"></div>
            </div>

            <div className="relative z-10 flex flex-col items-center justify-center min-h-screen p-6">

                {/* Main Card */}
                <div className="w-full max-w-4xl bg-white/5 backdrop-blur-2xl border border-white/10 rounded-[2.5rem] shadow-2xl overflow-hidden flex flex-col md:flex-row h-[80vh]">

                    {/* Left Panel - Controls & Info */}
                    <div className="w-full md:w-1/3 bg-black/20 p-8 flex flex-col justify-between border-r border-white/5">
                        <div>
                            <div className="flex items-center gap-3 mb-8">
                                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg">
                                    <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path></svg>
                                </div>
                                <h1 className="text-2xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
                                    SpeechSync
                                </h1>
                            </div>

                            <div className="space-y-6">
                                <div>
                                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Status</h3>
                                    <div className="flex items-center gap-3 bg-white/5 p-3 rounded-2xl border border-white/5">
                                        <span className={`w-3 h-3 rounded-full shadow-lg ${getStatusColor()}`}></span>
                                        <span className="text-sm font-medium text-slate-200">{getStatusText()}</span>
                                    </div>
                                </div>

                                <div>
                                    <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Controls</h3>
                                    <AudioRecorder
                                        onTranscript={handleTranscript}
                                        onError={(err) => setError(err)}
                                        onStatusChange={setStatus}
                                    />
                                </div>
                            </div>
                        </div>

                        <div className="mt-auto pt-8">
                            {error && (
                                <div className="p-4 bg-rose-500/10 border border-rose-500/20 text-rose-200 rounded-2xl text-xs leading-relaxed backdrop-blur-md">
                                    ⚠️ {error}
                                </div>
                            )}
                            <p className="mt-6 text-xs text-slate-500 text-center">
                                Powered by Gemini & Google Cloud
                            </p>
                        </div>
                    </div>

                    {/* Right Panel - Transcript */}
                    <div className="w-full md:w-2/3 p-8 md:p-12 flex flex-col bg-gradient-to-br from-white/5 to-transparent relative">
                        <h2 className="text-lg font-medium text-slate-400 mb-6 flex items-center gap-2">
                            <span>Live Transcript</span>
                            <div className="h-px bg-white/10 flex-grow"></div>
                        </h2>

                        <div className="flex-grow overflow-y-auto scrollbar-hide space-y-4 pr-2">
                            {transcript ? (
                                <p className="text-2xl md:text-3xl font-light leading-relaxed text-slate-100 tracking-wide animate-in fade-in slide-in-from-bottom-4 duration-500">
                                    {transcript}
                                    <span className="inline-block w-2 h-8 ml-1 align-middle bg-indigo-400 animate-pulse rounded-full"></span>
                                </p>
                            ) : (
                                <div className="h-full flex flex-col items-center justify-center text-slate-600 space-y-4 opacity-50">
                                    <div className="p-6 rounded-full bg-white/5 border border-white/5">
                                        <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"></path></svg>
                                    </div>
                                    <p className="text-lg font-light">Waiting for speech...</p>
                                </div>
                            )}
                        </div>
                    </div>

                </div>
            </div>

            {/* CSS for custom scrollbar if needed, though 'scrollbar-hide' class assumes tailwind-scrollbar-hide plugin or custom utility */}
            <style jsx global>{`
        @keyframes blob {
          0% { transform: translate(0px, 0px) scale(1); }
          33% { transform: translate(30px, -50px) scale(1.1); }
          66% { transform: translate(-20px, 20px) scale(0.9); }
          100% { transform: translate(0px, 0px) scale(1); }
        }
        .animate-blob {
          animation: blob 7s infinite;
        }
        .animation-delay-2000 {
          animation-delay: 2s;
        }
        .animation-delay-4000 {
          animation-delay: 4s;
        }
      `}</style>
        </main>
    );
}
