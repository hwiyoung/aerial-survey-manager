import { MapPinned, X } from 'lucide-react';
import { EO_CRS_OPTIONS, formatCrsLabel } from '../../constants/crs';

export default function CrsCorrectionModal({
    isOpen,
    projectTitle = '',
    currentSourceCrs = null,
    crsCorrection = {},
    eoDisplaySourceCrs = null,
    selectedCrs = 'EPSG:5186',
    onSelectedCrsChange,
    onClose,
    onReserve,
    onCancel,
    isSaving = false,
    error = '',
}) {
    if (!isOpen) return null;

    const hasPendingCrsCorrection = crsCorrection.status === 'pending' && Boolean(crsCorrection.sourceCrs);
    const correctedEoDisplaySourceCrs = eoDisplaySourceCrs || crsCorrection.eoDisplaySourceCrs || crsCorrection.sourceCrs;

    return (
        <div
            className="fixed inset-0 z-[10000] flex items-center justify-center bg-slate-950/45 px-4 backdrop-blur-sm"
            onClick={onClose}
        >
            <div
                className="w-full max-w-lg overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4">
                    <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-amber-100 bg-amber-50 text-amber-600">
                        <MapPinned size={20} />
                    </div>
                    <div className="min-w-0 flex-1">
	                        <h3 className="text-base font-bold text-slate-900">좌표계 변경</h3>
                        {projectTitle && (
                            <p className="mt-0.5 truncate text-xs font-medium text-slate-400">{projectTitle}</p>
                        )}
	                        <p className="mt-2 text-sm leading-5 text-slate-600">
	                            EO 파일의 원본 좌표가 실제로 사용하는 좌표계를 선택하세요. 처음 업로드할 때 잘못 선택했던 값이 아니라 원본 좌표의 기준입니다.
	                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="rounded-md p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                        aria-label="닫기"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div className="space-y-4 px-5 py-4">
                    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                        기존 처리 좌표계:{' '}
                        <span className="font-bold text-slate-900">{formatCrsLabel(currentSourceCrs)}</span>
                    </div>

                    <div className="rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-medium text-blue-700">
	                        최종 결과 저장 전까지 다시 바꾸거나 취소할 수 있습니다.
                    </div>

                    {hasPendingCrsCorrection && (
                        <div className="space-y-1 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                            <div>
	                                예약된 좌표계:{' '}
                                <span className="font-bold">{formatCrsLabel(crsCorrection.sourceCrs)}</span>
                            </div>
                            {correctedEoDisplaySourceCrs && (
                                <div className="text-xs font-semibold text-amber-700">
	                                    지도에 보이는 EO 위치도 {formatCrsLabel(correctedEoDisplaySourceCrs)} 기준으로 맞춰졌습니다.
                                </div>
                            )}
                        </div>
                    )}

                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                        {EO_CRS_OPTIONS.map((option) => {
                            const selected = selectedCrs === option.value;
                            return (
                                <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => onSelectedCrsChange?.(option.value)}
                                    disabled={isSaving}
                                    className={`min-h-12 rounded-lg border px-3 py-2 text-sm font-bold transition-colors
                                        ${selected
                                            ? 'border-amber-500 bg-amber-50 text-amber-800 ring-2 ring-amber-100'
                                            : 'border-slate-200 bg-white text-slate-600 hover:border-amber-300 hover:bg-amber-50'}`}
                                >
                                    {option.label}
                                </button>
                            );
                        })}
                    </div>

                    {error && (
                        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs font-medium text-red-700">
                            {error}
                        </div>
                    )}
                </div>

                <div className="flex gap-2 border-t border-slate-100 bg-slate-50 px-5 py-4">
                    {hasPendingCrsCorrection && (
                        <button
                            type="button"
                            onClick={onCancel}
                            disabled={isSaving}
                            className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-wait disabled:opacity-60"
                        >
	                            변경 취소
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={onClose}
                        disabled={isSaving}
                        className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-bold text-slate-600 transition-colors hover:bg-slate-100 disabled:cursor-wait disabled:opacity-60"
                    >
                        닫기
                    </button>
                    <button
                        type="button"
                        onClick={onReserve}
                        disabled={isSaving}
                        className="flex-[1.4] rounded-lg bg-amber-600 px-3 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-amber-700 disabled:cursor-wait disabled:bg-amber-300"
                    >
	                        {isSaving ? '저장 중...' : '변경 예약'}
                    </button>
                </div>
            </div>
        </div>
    );
}
