import { create } from 'zustand';
import { AgentFormatType, SessionItem } from '../types/session';

interface AppState {
  // Filters & Sorting
  activeFilter: AgentFormatType;
  setActiveFilter: (fmt: AgentFormatType) => void;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  sortField: string;
  setSortField: (f: string) => void;
  sortOrder: 'asc' | 'desc';
  toggleSortOrder: () => void;

  // Selected for Batch Operations
  selectedCatalogIds: string[];
  toggleSelectSession: (id: string) => void;
  selectAllSessions: (ids: string[]) => void;
  clearSelectedSessions: () => void;

  // Modals & Drawers
  activeDetailCatalogId: string | null;
  activeDetailTurnIndex: number | null;
  openSessionDetail: (catalogId: string, turnIndex?: number) => void;
  closeSessionDetail: () => void;

  isGlobalSearchOpen: boolean;
  setIsGlobalSearchOpen: (open: boolean) => void;

  isRootsModalOpen: boolean;
  setIsRootsModalOpen: (open: boolean) => void;

  isBatchDrawerOpen: boolean;
  setIsBatchDrawerOpen: (open: boolean) => void;

  activeSubagentParent: SessionItem | null;
  setActiveSubagentParent: (sess: SessionItem | null) => void;

  activeMigrateSession: SessionItem | null;
  setActiveMigrateSession: (sess: SessionItem | null) => void;

  /** 全量扫描进行中：后端会持有写锁，期间其他请求会变慢，UI 需要提示并收敛交互 */
  isScanning: boolean;
  setIsScanning: (v: boolean) => void;

  /** 折叠 Antigravity 同一对话的分叉快照，只保留主副本 */
  foldLineage: boolean;
  toggleFoldLineage: () => void;

  /** 任意组件改动数据后自增，列表据此重新拉取 */
  dataVersion: number;
  bumpDataVersion: () => void;
}

export const useStore = create<AppState>((set) => ({
  activeFilter: 'all',
  setActiveFilter: (fmt) => set({ activeFilter: fmt }),
  searchQuery: '',
  setSearchQuery: (q) => set({ searchQuery: q }),
  sortField: 'mtime',
  setSortField: (f) => set({ sortField: f }),
  sortOrder: 'desc',
  toggleSortOrder: () => set((s) => ({ sortOrder: s.sortOrder === 'desc' ? 'asc' : 'desc' })),

  selectedCatalogIds: [],
  toggleSelectSession: (id) =>
    set((s) => ({
      selectedCatalogIds: s.selectedCatalogIds.includes(id)
        ? s.selectedCatalogIds.filter((x) => x !== id)
        : [...s.selectedCatalogIds, id],
    })),
  selectAllSessions: (ids) => set({ selectedCatalogIds: ids }),
  clearSelectedSessions: () => set({ selectedCatalogIds: [] }),

  activeDetailCatalogId: null,
  activeDetailTurnIndex: null,
  openSessionDetail: (catalogId, turnIndex = undefined) =>
    set({ activeDetailCatalogId: catalogId, activeDetailTurnIndex: turnIndex ?? null }),
  closeSessionDetail: () =>
    set({ activeDetailCatalogId: null, activeDetailTurnIndex: null }),

  isGlobalSearchOpen: false,
  setIsGlobalSearchOpen: (open) => set({ isGlobalSearchOpen: open }),

  isRootsModalOpen: false,
  setIsRootsModalOpen: (open) => set({ isRootsModalOpen: open }),

  isBatchDrawerOpen: false,
  setIsBatchDrawerOpen: (open) => set({ isBatchDrawerOpen: open }),

  activeSubagentParent: null,
  setActiveSubagentParent: (sess) => set({ activeSubagentParent: sess }),

  activeMigrateSession: null,
  setActiveMigrateSession: (sess) => set({ activeMigrateSession: sess }),

  isScanning: false,
  setIsScanning: (v) => set({ isScanning: v }),

  foldLineage: false,
  toggleFoldLineage: () => set((s) => ({ foldLineage: !s.foldLineage })),

  dataVersion: 0,
  bumpDataVersion: () => set((s) => ({ dataVersion: s.dataVersion + 1 })),
}));
