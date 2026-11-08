// @vitest-environment jsdom
import {describe,it,expect,vi,afterEach} from 'vitest';
import {render,screen,cleanup} from '@testing-library/react';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {MemoryRouter} from 'react-router-dom';
import {DiagramChooser} from './GraphPage';
vi.mock('../../api/client',()=>({isMock:true,api:{getCatalog:vi.fn(async()=>({run_id:'run',items:[{type:'directory',availability:'available',reason:null},{type:'erd',availability:'unsupported',reason:'DDL 없음'}]}))}}));
afterEach(()=>cleanup());
describe('다이어그램 선택 화면',()=>{it('지원하지 않는 유형을 비활성화하고 사유를 표시한다',async()=>{const client=new QueryClient({defaultOptions:{queries:{retry:false}}});render(<QueryClientProvider client={client}><MemoryRouter><DiagramChooser runId="run"/></MemoryRouter></QueryClientProvider>);const unsupported=await screen.findByRole('button',{name:/ERD 미지원/});expect((unsupported as HTMLButtonElement).disabled).toBe(true);expect(unsupported.textContent).toContain('DDL 없음');expect(screen.getByRole('button',{name:/폴더 구조/})).toBeTruthy()})});
