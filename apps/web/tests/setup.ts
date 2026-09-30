import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';

function storage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key) => map.get(key) ?? null,
    key: (index) => [...map.keys()][index] ?? null,
    removeItem: (key) => {
      map.delete(key);
    },
    setItem: (key, value) => {
      map.set(key, value);
    },
  };
}

if (typeof DataTransfer === 'undefined') {
  class DataTransferPolyfill {
    private readonly filesList: File[] = [];
    items = {
      add: (file: File) => {
        this.filesList.push(file);
      },
    };
    get files(): FileList {
      const list = {
        length: this.filesList.length,
        item: (index: number) => this.filesList[index] ?? null,
      } as FileList;
      this.filesList.forEach((file, index) => {
        Object.defineProperty(list, index, { value: file });
      });
      return list;
    }
  }
  Object.defineProperty(globalThis, 'DataTransfer', { value: DataTransferPolyfill, writable: true });
}

beforeEach(() => {
  Object.defineProperty(window, 'localStorage', { configurable: true, value: storage(), writable: true });
  Element.prototype.scrollIntoView = () => {};
});

afterEach(() => {
  cleanup();
});
