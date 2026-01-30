'use client';

import { useState, useRef, useEffect } from 'react';

interface AudioRecorderProps {
    onTranscript: (text: string, isFinal: boolean) => void;
    onError: (error: string) => void;
    onStatusChange: (status: 'disconnected' | 'connecting' | 'connected' | 'recording') => void;
}

export default function AudioRecorder({ onTranscript, onError, onStatusChange }: AudioRecorderProps) {
    const [isRecording, setIsRecording] = useState(false);
    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const socketRef = useRef<WebSocket | null>(null);

    // Connect to WebSocket on mount
    useEffect(() => {
        connectWebSocket();
        return () => {
            if (socketRef.current) {
                socketRef.current.close();
            }
        };
    }, []);

    const connectWebSocket = () => {
        onStatusChange('connecting');
        const ws = new WebSocket('ws://localhost:8000');

        ws.onopen = () => {
            console.log('Connected to WebSocket');
            onStatusChange('connected');
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.transcript) {
                    onTranscript(data.transcript, data.isFinal);
                } else if (data.error) {
                    onError(data.error);
                }
            } catch (e) {
                console.error('Failed to parse message:', event.data);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected');
            onStatusChange('disconnected');
            setIsRecording(false);
            // Auto-reconnect after 3 seconds
            setTimeout(connectWebSocket, 3000);
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            onError('WebSocket connection error');
        };

        socketRef.current = ws;
    };

    const startRecording = async () => {
        try {
            if (!navigator || !navigator.mediaDevices) {
                throw new Error("Microphone access is not supported. Ensure you are using HTTPS or localhost.");
            }
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            const mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });

            mediaRecorderRef.current = mediaRecorder;

            mediaRecorder.ondataavailable = async (event) => {
                if (event.data.size > 0 && socketRef.current?.readyState === WebSocket.OPEN) {
                    socketRef.current.send(event.data);
                }
            };

            mediaRecorder.start(250); // Send chunks every 250ms
            setIsRecording(true);
            onStatusChange('recording');
        } catch (err) {
            console.error('Error accessing microphone:', err);
            onError('Could not access microphone.');
        }
    };

    const stopRecording = () => {
        if (mediaRecorderRef.current && isRecording) {
            mediaRecorderRef.current.stop();
            mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
            setIsRecording(false);
            if (socketRef.current?.readyState === WebSocket.OPEN) {
                onStatusChange('connected');
            } else {
                onStatusChange('disconnected');
            }
        }
    };

    return (
        <div className="flex flex-col items-center gap-4 w-full">
            <button
                onClick={isRecording ? stopRecording : startRecording}
                className={`w-full py-4 rounded-xl font-semibold text-white tracking-wide transition-all duration-300 shadow-lg hover:shadow-2xl hover:-translate-y-1 active:scale-95 flex items-center justify-center gap-3 ${isRecording
                    ? 'bg-gradient-to-r from-rose-500 to-pink-600 shadow-rose-500/30'
                    : 'bg-gradient-to-r from-indigo-500 to-purple-600 shadow-indigo-500/30 hover:shadow-indigo-500/50'
                    }`}
            >
                {isRecording ? (
                    <>
                        <span className="relative flex h-3 w-3">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-3 w-3 bg-white"></span>
                        </span>
                        <span>Stop Recording</span>
                    </>
                ) : (
                    <>
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"></path></svg>
                        <span>Start Recording</span>
                    </>
                )}
            </button>
            {isRecording && (
                <p className="text-xs text-rose-300 animate-pulse font-medium tracking-wide">● Recording in progress...</p>
            )}
        </div>
    );
}
