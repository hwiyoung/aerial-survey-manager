import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Folder, FileImage, FileText, ChevronRight, ArrowUp, X, CheckCircle2, Loader2, AlertCircle, Image as ImageIcon, CheckSquare, Square, HardDrive, Info, RefreshCw } from 'lucide-react';
import api from '../../api/client';

/**
 * ServerFileBrowser - a modal dialog that browses the server's filesystem via API.
 *
 * Props:
 *   isOpen      - boolean controlling visibility
 *   onClose     - callback to close the modal
 *   onSelect    - callback({ path, imageCount }) for folder mode
 *                 callback({ path, filePaths }) for files mode
 *                 callback({ path, filePath }) for eo mode (single file)
 *   mode        - 'folder' (select entire directory) or 'files' (select individual images) or 'eo' (single text file)
 *   fileTypes   - 'images' (default) or 'eo' — controls which file extensions are shown
 *   initialPath - optional directory path to open instead of roots view
 */
export default function ServerFileBrowser({ isOpen, onClose, onSelect, mode = 'folder', fileTypes = 'images', initialPath = null }) {
    const [currentPath, setCurrentPath] = useState('');
    const [parentPath, setParentPath] = useState(null);
    const [entries, setEntries] = useState([]);
    const [imageCount, setImageCount] = useState(0);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [selectedFiles, setSelectedFiles] = useState(new Set());
    const [roots, setRoots] = useState([]);
    const [isRootsView, setIsRootsView] = useState(true);
    const [rootsHint, setRootsHint] = useState('');
    const [lastClickedIndex, setLastClickedIndex] = useState(-1);

    const fetchRoots = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await api.getFilesystemRoots();
            setRoots(data.roots);
            setRootsHint(data.hint);
            setIsRootsView(true);
            setEntries([]);
            setImageCount(0);
            setCurrentPath('');
            setParentPath(null);
            setSelectedFiles(new Set());
            setLastClickedIndex(-1);
        } catch (err) {
            setError(err.message || '디바이스 목록을 불러올 수 없습니다');
        } finally {
            setLoading(false);
        }
    }, []);

    const fetchDirectory = useCallback(async (path) => {
        setLoading(true);
        setError(null);
        setSelectedFiles(new Set());
        setLastClickedIndex(-1);
        try {
            const data = await api.browseFilesystem(path, fileTypes);
            setCurrentPath(data.current_path);
            setParentPath(data.parent_path);
            setEntries(data.entries);
            setImageCount(data.image_count);
            setIsRootsView(false);
        } catch (err) {
            setError(err.message || 'Failed to browse directory');
            setEntries([]);
            setImageCount(0);
        } finally {
            setLoading(false);
        }
    }, [fileTypes]);

    useEffect(() => {
        if (isOpen) {
            if (initialPath) {
                fetchDirectory(initialPath);
            } else {
                fetchRoots();
            }
        }
    }, [isOpen, initialPath, fetchRoots, fetchDirectory]);

    useEffect(() => {
        if (!isOpen) return;
        const handleKeyDown = (e) => {
            if (e.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, onClose]);

    const handleNavigate = (path) => {
        fetchDirectory(path);
    };

    const handleGoUp = () => {
        if (parentPath) {
            fetchDirectory(parentPath);
        } else if (!isRootsView) {
            fetchRoots();
        }
    };

    const isExternalDrive = (path) => /^\/(media|mnt)\//i.test(path);

    const handleSelect = () => {
        const doSelect = () => {
            if (mode === 'eo') {
                const filePath = Array.from(selectedFiles)[0];
                if (filePath) {
                    onSelect({ path: currentPath, filePath });
                }
            } else if (mode === 'files') {
                onSelect({ path: currentPath, filePaths: Array.from(selectedFiles) });
            } else {
                onSelect({ path: currentPath, imageCount });
            }
            onClose();
        };

        if (mode !== 'eo' && isExternalDrive(currentPath)) {
            const ok = window.confirm(
                '⚠️ 외장 하드디스크 경로가 감지되었습니다.\n\n' +
                '외장 저장장치의 I/O 속도에 따라 이미지 처리 시간이 길어질 수 있습니다.\n' +
                '가능하면 내장 디스크로 복사 후 진행하는 것을 권장합니다.\n\n' +
                '이대로 진행하시겠습니까?'
            );
            if (!ok) return;
        }
        doSelect();
    };

    const directories = entries.filter(e => e.is_dir);
    const files = entries.filter(e => !e.is_dir);

    // Map file path to index for Shift+Click range selection
    const fileIndexMap = useMemo(() => {
        const map = {};
        files.forEach((f, idx) => { map[f.path] = idx; });
        return map;
    }, [files]);

    const handleFileClick = (filePath, event) => {
        const index = fileIndexMap[filePath];
        if (index === undefined) return;

        // EO mode: single file selection only
        if (mode === 'eo') {
            setSelectedFiles(new Set([filePath]));
            setLastClickedIndex(index);
            return;
        }

        if (event.shiftKey && lastClickedIndex >= 0) {
            // Shift+Click: range select
            const start = Math.min(lastClickedIndex, index);
            const end = Math.max(lastClickedIndex, index);
            const rangeFiles = files.slice(start, end + 1).map(f => f.path);
            setSelectedFiles(prev => {
                const next = new Set(prev);
                rangeFiles.forEach(fp => next.add(fp));
                return next;
            });
        } else if (event.ctrlKey || event.metaKey) {
            // Ctrl+Click: toggle individual (keep others)
            setSelectedFiles(prev => {
                const next = new Set(prev);
                if (next.has(filePath)) {
                    next.delete(filePath);
                } else {
                    next.add(filePath);
                }
                return next;
            });
            setLastClickedIndex(index);
        } else {
            // Regular click: select only this file
            setSelectedFiles(new Set([filePath]));
            setLastClickedIndex(index);
        }
    };

    const allFilesSelected = files.length > 0 && files.every(f => selectedFiles.has(f.path));

    const toggleSelectAll = () => {
        if (allFilesSelected) {
            setSelectedFiles(new Set());
        } else {
            setSelectedFiles(new Set(files.map(f => f.path)));
        }
    };

    const breadcrumbs = currentPath ? currentPath.split('/').filter(Boolean) : [];
    const breadcrumbPaths = breadcrumbs.map((_, i) => '/' + breadcrumbs.slice(0, i + 1).join('/'));

    const formatSize = (bytes) => {
        if (!bytes && bytes !== 0) return '';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    };

    const canConfirm = isRootsView ? false : (mode === 'files' || mode === 'eo' ? selectedFiles.size > 0 : true);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200" onClick={onClose}>
            <div className="bg-white rounded-xl shadow-2xl w-[720px] max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div className="h-14 border-b border-slate-200 flex items-center justify-between px-5 bg-slate-50 rounded-t-xl shrink-0">
                    <h3 className="font-bold text-slate-800 flex items-center gap-2">
                        <Folder size={18} className="text-blue-600" />
                        {mode === 'eo' ? 'EO 파일 선택' : mode === 'folder' ? '이미지 폴더 선택' : '개별 이미지 선택'}
                    </h3>
                    <button onClick={onClose} className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded-lg transition-colors" title="닫기">
                        <X size={18} />
                    </button>
                </div>

                {/* Breadcrumb / Path bar */}
                <div className="px-5 py-2.5 border-b border-slate-100 bg-white flex items-center gap-1 text-sm overflow-x-auto shrink-0">
                    {isRootsView ? (
                        <span className="text-slate-800 font-bold px-1.5 py-0.5 flex items-center gap-1.5">
                            <HardDrive size={14} className="text-blue-600" /> 마운트된 디스크
                        </span>
                    ) : (
                        <>
                            <button
                                onClick={() => fetchRoots()}
                                className="text-blue-600 hover:text-blue-800 font-medium shrink-0 hover:bg-blue-50 px-1.5 py-0.5 rounded transition-colors flex items-center gap-1"
                            >
                                <HardDrive size={14} /> 디스크
                            </button>
                            {breadcrumbs.map((segment, i) => (
                                <React.Fragment key={i}>
                                    <ChevronRight size={14} className="text-slate-300 shrink-0" />
                                    <button
                                        onClick={() => handleNavigate(breadcrumbPaths[i])}
                                        className={`shrink-0 px-1.5 py-0.5 rounded transition-colors font-mono ${
                                            i === breadcrumbs.length - 1
                                                ? 'text-slate-800 font-bold bg-slate-100'
                                                : 'text-blue-600 hover:text-blue-800 hover:bg-blue-50'
                                        }`}
                                    >
                                        {segment}
                                    </button>
                                </React.Fragment>
                            ))}
                        </>
                    )}
                </div>

                {/* Navigation bar */}
                <div className="px-5 py-2 border-b border-slate-100 flex items-center justify-between shrink-0">
                    <div className="flex items-center gap-3">
                        <button
                            onClick={handleGoUp}
                            disabled={isRootsView}
                            className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-blue-600 disabled:text-slate-300 disabled:cursor-not-allowed transition-colors px-2 py-1 rounded hover:bg-slate-100"
                        >
                            <ArrowUp size={16} /> {!parentPath && !isRootsView ? '디스크 목록' : '상위 폴더'}
                        </button>
                        {isRootsView && (
                            <button
                                onClick={() => fetchRoots()}
                                className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-blue-600 transition-colors px-2 py-1 rounded hover:bg-slate-100"
                            >
                                <RefreshCw size={14} /> 새로고침
                            </button>
                        )}
                        {mode === 'files' && files.length > 0 && !isRootsView && (
                            <button
                                onClick={toggleSelectAll}
                                className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-blue-600 transition-colors px-2 py-1 rounded hover:bg-slate-100"
                            >
                                {allFilesSelected ? <CheckSquare size={16} className="text-blue-600" /> : <Square size={16} />}
                                {allFilesSelected ? '전체 해제' : '전체 선택'}
                            </button>
                        )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-slate-400">
                        {!isRootsView && directories.length > 0 && (
                            <span className="flex items-center gap-1"><Folder size={13} /> {directories.length}개 폴더</span>
                        )}
                        {!isRootsView && ((mode === 'files' || mode === 'eo') && selectedFiles.size > 0 ? (
                            <span className="flex items-center gap-1 text-blue-600 font-bold">{mode === 'eo' ? <FileText size={13} /> : <ImageIcon size={13} />} {selectedFiles.size}개 선택됨</span>
                        ) : imageCount > 0 && (
                            <span className="flex items-center gap-1 text-blue-500 font-medium">{fileTypes === 'eo' ? <FileText size={13} /> : <ImageIcon size={13} />} {imageCount}개 파일</span>
                        ))}
                    </div>
                </div>

                {/* File listing */}
                <div className="flex-1 overflow-y-auto min-h-[300px] select-none">
                    {loading && (
                        <div className="flex items-center justify-center h-full py-20">
                            <Loader2 size={28} className="animate-spin text-blue-500" />
                            <span className="ml-3 text-slate-500">불러오는 중...</span>
                        </div>
                    )}

                    {error && (
                        <div className="m-5 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
                            <AlertCircle size={18} className="shrink-0" /> {error}
                        </div>
                    )}

                    {/* Roots view - mounted devices */}
                    {!loading && !error && isRootsView && (
                        <div className="p-5 space-y-3">
                            {rootsHint && (
                                <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-700 text-sm flex items-center gap-2">
                                    <Info size={16} className="shrink-0" />
                                    {rootsHint}
                                </div>
                            )}
                            {roots.map((root) => (
                                <div
                                    key={root.path}
                                    onClick={() => handleNavigate(root.path)}
                                    className="flex items-center gap-4 p-4 border border-slate-200 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-300 transition-colors"
                                >
                                    <HardDrive size={28} className="text-blue-600 shrink-0" />
                                    <div className="flex-1 min-w-0">
                                        <div className="font-bold text-slate-700 text-base">{root.name}</div>
                                        <div className="text-xs text-slate-400 font-mono truncate">{root.path}</div>
                                        {root.total_gb != null && root.total_gb > 0 && (
                                            <div className="mt-1.5 flex items-center gap-2">
                                                <div className="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                                                    <div
                                                        className={`h-full rounded-full ${
                                                            (root.used_gb / root.total_gb) > 0.9 ? 'bg-red-500' :
                                                            (root.used_gb / root.total_gb) > 0.7 ? 'bg-amber-500' : 'bg-blue-500'
                                                        }`}
                                                        style={{ width: `${Math.min(100, (root.used_gb / root.total_gb) * 100)}%` }}
                                                    />
                                                </div>
                                                <span className="text-[10px] text-slate-400 shrink-0 whitespace-nowrap">
                                                    {root.used_gb}GB / {root.total_gb}GB
                                                </span>
                                            </div>
                                        )}
                                    </div>
                                    <ChevronRight size={18} className="text-slate-300 shrink-0" />
                                </div>
                            ))}
                            {roots.length === 0 && (
                                <div className="text-center py-10 text-slate-400">
                                    <HardDrive size={48} className="mx-auto mb-3 opacity-30" />
                                    <p className="text-sm">마운트된 디스크를 찾을 수 없습니다</p>
                                    <p className="text-xs mt-1">외장하드를 연결한 후 새로고침 해주세요</p>
                                </div>
                            )}
                        </div>
                    )}

                    {/* Directory contents */}
                    {!loading && !error && !isRootsView && entries.length === 0 && (
                        <div className="flex flex-col items-center justify-center h-full py-20 text-slate-400">
                            <Folder size={48} className="mb-3 opacity-30" />
                            <p className="text-sm">이 폴더는 비어 있습니다</p>
                        </div>
                    )}

                    {!loading && !error && !isRootsView && entries.length > 0 && (
                        <div className="divide-y divide-slate-50">
                            {entries.map((entry) => (
                                <div
                                    key={entry.path}
                                    className={`flex items-center gap-3 px-5 py-2.5 cursor-pointer transition-colors group ${
                                        entry.is_dir
                                            ? 'hover:bg-blue-50'
                                            : selectedFiles.has(entry.path)
                                                ? 'bg-blue-50 border-l-2 border-l-blue-500'
                                                : 'hover:bg-slate-50'
                                    }`}
                                    onClick={(e) => {
                                        if (entry.is_dir) {
                                            handleNavigate(entry.path);
                                        } else if (mode === 'files' || mode === 'eo') {
                                            handleFileClick(entry.path, e);
                                        }
                                    }}
                                >
                                    {(mode === 'files' || mode === 'eo') && !entry.is_dir && (
                                        selectedFiles.has(entry.path)
                                            ? <CheckSquare size={18} className="text-blue-600 shrink-0" />
                                            : <Square size={18} className="text-slate-300 shrink-0" />
                                    )}
                                    {entry.is_dir ? (
                                        <Folder size={20} className="text-amber-500 shrink-0" />
                                    ) : fileTypes === 'eo' ? (
                                        <FileText size={20} className="text-blue-500 shrink-0" />
                                    ) : (
                                        <FileImage size={20} className="text-emerald-500 shrink-0" />
                                    )}
                                    <div className={`flex-1 min-w-0 ${
                                        entry.is_dir
                                            ? 'text-slate-700 font-medium group-hover:text-blue-700'
                                            : selectedFiles.has(entry.path) ? 'text-blue-700 font-medium' : 'text-slate-600'
                                    }`}>
                                        <span className="text-sm truncate block">{entry.name}</span>
                                    </div>
                                    {!entry.is_dir && entry.size != null && (
                                        <span className="text-xs text-slate-400 shrink-0">{formatSize(entry.size)}</span>
                                    )}
                                    {entry.is_dir && (
                                        <ChevronRight size={16} className="text-slate-300 group-hover:text-blue-400 shrink-0" />
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Footer with action buttons */}
                <div className="border-t border-slate-200 px-5 py-3 flex items-center justify-between bg-slate-50 rounded-b-xl shrink-0">
                    <div className="flex flex-col gap-0.5">
                        <div className="text-sm text-slate-500 font-mono truncate max-w-[400px]" title={currentPath}>
                            {isRootsView ? '디스크를 선택하세요' : currentPath}
                        </div>
                        {mode === 'files' && !isRootsView && files.length > 0 && (
                            <div className="text-[10px] text-slate-400">
                                Ctrl+클릭: 개별 선택 · Shift+클릭: 범위 선택
                            </div>
                        )}
                        {mode === 'eo' && !isRootsView && selectedFiles.size > 0 && (
                            <div className="text-[10px] text-emerald-600 font-medium">
                                파일이 선택되었습니다
                            </div>
                        )}
                    </div>
                    <div className="flex items-center gap-3">
                        <button
                            onClick={onClose}
                            className="px-4 py-2 text-slate-500 hover:text-slate-700 text-sm font-medium hover:bg-slate-200 rounded-lg transition-colors"
                        >
                            취소
                        </button>
                        <button
                            onClick={handleSelect}
                            disabled={!canConfirm}
                            className="px-5 py-2 bg-blue-600 text-white rounded-lg font-bold text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm flex items-center gap-2"
                        >
                            <CheckCircle2 size={16} />
                            {mode === 'eo' ? (
                                <>파일 선택</>
                            ) : mode === 'files' ? (
                                <>선택 완료 {selectedFiles.size > 0 && <span className="bg-blue-500 text-white text-xs px-1.5 py-0.5 rounded-full ml-1">{selectedFiles.size}</span>}</>
                            ) : (
                                <>이 폴더 선택 {imageCount > 0 && <span className="bg-blue-500 text-white text-xs px-1.5 py-0.5 rounded-full ml-1">{imageCount}</span>}</>
                            )}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
