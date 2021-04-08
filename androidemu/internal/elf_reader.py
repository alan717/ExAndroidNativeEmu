import struct
import os
import sys

from ..utils import memory_helpers,misc_utils
from ..utils.misc_utils import get_segment_protection,page_end, page_start

PT_NULL   = 0
PT_LOAD   = 1
PT_DYNAMIC =2
PT_INTERP  =3
PT_NOTE    =4
PT_SHLIB   =5
PT_PHDR    =6


DT_NULL	=0
DT_NEEDED	=1
DT_PLTRELSZ	=2
DT_PLTGOT	=3
DT_HASH		=4
DT_STRTAB	=5
DT_SYMTAB	=6
DT_RELA		=7
DT_RELASZ	=8
DT_RELAENT	=9
DT_STRSZ	=10
DT_SYMENT	=11
DT_INIT =0x0c
DT_INIT_ARRAY =0x19
DT_FINI_ARRAY =0x1a
DT_INIT_ARRAYSZ =0x1b
DT_FINI_ARRAYSZ =0x1c
DT_SONAME	=14
DT_RPATH 	=15
DT_SYMBOLIC	=16
DT_REL	    =17
DT_RELSZ	=18
DT_RELENT	=19
DT_PLTREL	=20
DT_DEBUG	=21
DT_TEXTREL	=22
DT_JMPREL	=23
DT_GNU_HASH = 0x6ffffef5
DT_LOPROC	=0x70000000
DT_HIPROC	=0x7fffffff

SHN_UNDEF	=0
SHN_LORESERVE	=0xff00
SHN_LOPROC	=0xff00
SHN_HIPROC	=0xff1f
SHN_ABS	=0xfff1
SHN_COMMON	=0xfff2
SHN_HIRESERVE	=0xffff
SHN_MIPS_ACCOMON	=0xff00

STB_LOCAL = 0
STB_GLOBAL =1
STB_WEAK   =2
STT_NOTYPE  =0
STT_OBJECT  =1
STT_FUNC    =2
STT_SECTION =3
STT_FILE    =4

class ELFReader:
    '''
    #define EI_NIDENT	16
    typedef struct elf32_hdr{
        unsigned char	e_ident[EI_NIDENT];
        Elf32_Half	e_type;
        Elf32_Half	e_machine;
        Elf32_Word	e_version;
        Elf32_Addr	e_entry;  /* Entry point */
        Elf32_Off	e_phoff;
        Elf32_Off	e_shoff;
        Elf32_Word	e_flags;
        Elf32_Half	e_ehsize;
        Elf32_Half	e_phentsize;
        Elf32_Half	e_phnum;
        Elf32_Half	e_shentsize;
        Elf32_Half	e_shnum;
        Elf32_Half	e_shstrndx;
    } Elf32_Ehdr;

    typedef struct elf32_phdr{
        Elf32_Word	p_type;
        Elf32_Off	p_offset;
        Elf32_Addr	p_vaddr;
        Elf32_Addr	p_paddr;
        Elf32_Word	p_filesz;
        Elf32_Word	p_memsz;
        Elf32_Word	p_flags;
        Elf32_Word	p_align;
    } Elf32_Phdr;

    typedef struct elf32_sym{
        Elf32_Word	st_name;
        Elf32_Addr	st_value;
        Elf32_Word	st_size;
        unsigned char	st_info;
        unsigned char	st_other;
        Elf32_Half	st_shndx;
        } Elf32_Sym;
    typedef struct elf32_rel {
        Elf32_Addr	r_offset;
        Elf32_Word	r_info;
    } Elf32_Rel;
    typedef struct elf64_rela{
        Elf64_Addr r_offset;	/* Location at which to apply the action */
        Elf64_Xword r_info;	/* index and type of relocation */
        Elf64_Sxword r_addend;	/* Constant addend used to compute value */
    } Elf64_Rela;
    '''
    @staticmethod
    def __elf32_r_sym(x):
        return x>>8
    #
    @staticmethod
    def __elf32_r_type(x):
        return x & 0xff
    #

#define ELF_ST_BIND(x)	((x) >> 4)
#define ELF_ST_TYPE(x)	(((unsigned int) x) & 0xf)

    @staticmethod
    def __elf_st_bind(x):
        return x >> 4
    #

    @staticmethod
    def __elf_st_type(x):
        return x & 0xf
    #

    def __st_name_to_name(self, st_name):
        assert st_name < self.__dyn_str_sz, "__st_name_to_name st_name %d out of range %d"%(st_name, self.__dyn_str_sz)
        endId=self.__dyn_str_buf.find(b"\x00", st_name)
        r = self.__dyn_str_buf[st_name:endId]
        name = r.decode("utf-8")
        return name
    #

    def __init__(self, filename):
    # 既然要模拟运行就不要再使用任何静态分析的东西了。
        with open(filename, 'rb') as f:
            ehdr32_sz = 52
            phdr32_sz = 32
            elf32_dyn_sz = 8
            elf32_sym_sz = 16
            elf32_rel_sz = 8

            self.__filename = filename
            self.__init_array_off = 0
            self.__init_array_size = 0
            self.__init_off = 0
            self.__nbucket = 0
            self.__nchain = 0
            self.__bucket = 0
            self.__chain = 0


            self.__phdrs = []
            self.__loads = []
            self.__dynsymols = []
            self.__rels = {}
            self.__file = f
            ehdr_bytes = f.read(ehdr32_sz)
            _, _ , _, _, _, phoff, _, _, _, _, phdr_num, _, _, _ = struct.unpack("<16sHHIIIIIHHHHHH", ehdr_bytes)

            print(phoff)
            self.__phoff = phoff
            self.__phdr_num = phdr_num
            f.seek(phoff, 0)

            dyn_off = 0
            self.__sz = 0
            min_vaddr=0xFFFFFFFF
            max_vaddr = 0x00000000

            for i in range(0, phdr_num):
                phdr_bytes = f.read(phdr32_sz)
                p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack("<IIIIIIII", phdr_bytes)
                phdr = {"p_type":p_type, "p_offset":p_offset, "p_vaddr":p_vaddr, "p_paddr":p_paddr, \
                                                "p_filesz":p_filesz, "p_memsz":p_memsz, "p_flags":p_flags, "p_align":p_align}

                self.__phdrs.append(phdr)
                if (p_type == PT_DYNAMIC):
                    dyn_off = p_vaddr
                #
                elif(p_type == PT_LOAD):
                    self.__loads.append(phdr)
                    if(p_vaddr<min_vaddr):
                        min_vaddr=p_vaddr
                    if(p_vaddr+p_memsz>max_vaddr):
                        max_vaddr=p_vaddr+p_memsz
                # ReserveAddressSpace
                # self.__sz += p_memsz
            min_vaddr = page_start(min_vaddr)
            max_vaddr = page_end(max_vaddr)
            self._sz=max_vaddr-min_vaddr
            #
            assert dyn_off > 0, "error no dynamic in this elf."
            self.__dyn_off = dyn_off

            f.seek(dyn_off, 0)
            dyn_str_off = 0
            dyn_str_sz = 0
            self.__dyn_str_buf = b""
            dyn_sym_off = -0
            nsymbol = -1
            rel_off = 0
            rel_count = 0
            relplt_off = 0
            relplt_count = 0

            #
        #
    #

    def get_load(self):
        return self.__loads
    #

    def get_symbols(self):
        return self.__dynsymols
    #

    def get_rels(self):
        return self.__rels
    #

    def get_dyn_string_by_rel_sym(self, rel_sym):
        nsym = len(self.__dynsymols)
        assert rel_sym < nsym
        sym =  self.__dynsymols[rel_sym]
        st_name = sym["st_name"]
        r = self.__st_name_to_name(st_name)
        return r
    #

    def get_init_array(self):
        return self.__init_array_off, self.__init_array_size
    #

    def get_init(self):
        return self.__init_off
    #

    def get_so_need(self):
        return None
    #

    #android 4.4.4 soinfo
    '''
    struct link_map_t {
        uintptr_t l_addr;
        char*  l_name;
        uintptr_t l_ld;
        link_map_t* l_next;
        link_map_t* l_prev;
    };

    #define SOINFO_NAME_LEN 128
    struct soinfo {
    public:
        char name[SOINFO_NAME_LEN];
        const Elf32_Phdr* phdr;
        size_t phnum;
        Elf32_Addr entry;
        Elf32_Addr base;
        unsigned size;
        uint32_t unused1;  // DO NOT USE, maintained for compatibility.
        Elf32_Dyn* dynamic;
        uint32_t unused2; // DO NOT USE, maintained for compatibility
        uint32_t unused3; // DO NOT USE, maintained for compatibility
        soinfo* next;
        unsigned flags;
        const char* strtab;
        Elf32_Sym* symtab;
        size_t nbucket;
        size_t nchain;
        unsigned* bucket;
        unsigned* chain;
        unsigned* plt_got;
        Elf32_Rel* plt_rel;
        size_t plt_rel_count;
        Elf32_Rel* rel;
        size_t rel_count;
        linker_function_t* preinit_array;
        size_t preinit_array_count;
        linker_function_t* init_array;
        size_t init_array_count;
        linker_function_t* fini_array;
        size_t fini_array_count;
        linker_function_t init_func;
        linker_function_t fini_func;
        
        // ARM EABI section used for stack unwinding.
        unsigned* ARM_exidx;
        size_t ARM_exidx_count;
        
        size_t ref_count;
        link_map_t link_map;
        bool constructors_called;
        // When you read a virtual address from the ELF file, add this
        // value to get the corresponding address in the process' address space.
        Elf32_Addr load_bias;
    };
    '''
    def write_soinfo(self, mu, load_base, info_base):

        #在虚拟机中构造一个soinfo结构
        assert len(self.__filename)<128
        
        #name
        memory_helpers.write_utf8(mu, info_base+0, self.__filename)
        #phdr
        mu.mem_write(info_base+128, int(load_base+self.__phoff).to_bytes(4, byteorder='little'))
        #phnum
        mu.mem_write(info_base+132, int(self.__phdr_num).to_bytes(4, byteorder='little'))
        #entry
        mu.mem_write(info_base+136, int(0).to_bytes(4, byteorder='little'))
        #base
        mu.mem_write(info_base+140, int(load_base).to_bytes(4, byteorder='little'))
        #size
        mu.mem_write(info_base+144, int(self.__sz).to_bytes(4, byteorder='little'))
        #unused1
        mu.mem_write(info_base+148, int(0).to_bytes(4, byteorder='little'))
        #dynamic
        mu.mem_write(info_base+152, int(load_base+self.__dyn_off).to_bytes(4, byteorder='little'))
        #unused2
        mu.mem_write(info_base+156, int(0).to_bytes(4, byteorder='little'))
        #unused3
        mu.mem_write(info_base+160, int(0).to_bytes(4, byteorder='little'))
        #next
        mu.mem_write(info_base+164, int(0).to_bytes(4, byteorder='little'))
        #flags
        mu.mem_write(info_base+168, int(0).to_bytes(4, byteorder='little'))
        #strtab
        mu.mem_write(info_base+172, int(load_base+self.__dyn_str_off).to_bytes(4, byteorder='little'))
        #symtab    
        mu.mem_write(info_base+176, int(load_base+self.__dym_sym_off).to_bytes(4, byteorder='little'))
        #nbucket
        mu.mem_write(info_base+180, int(self.__nbucket).to_bytes(4, byteorder='little'))
        #nchain
        mu.mem_write(info_base+184, int(self.__nchain).to_bytes(4, byteorder='little'))

        #bucket
        mu.mem_write(info_base+188, int(load_base+self.__bucket).to_bytes(4, byteorder='little'))
        #nchain
        mu.mem_write(info_base+192, int(load_base+self.__chain).to_bytes(4, byteorder='little'))

        #plt_got
        mu.mem_write(info_base+196, int(load_base+self.__plt_got).to_bytes(4, byteorder='little'))

        #plt_rel
        mu.mem_write(info_base+200, int(load_base+self.__pltrel).to_bytes(4, byteorder='little'))
        #plt_rel_count
        mu.mem_write(info_base+204, int(self.__pltrel_count).to_bytes(4, byteorder='little'))

        #rel
        mu.mem_write(info_base+208, int(load_base+self.__rel).to_bytes(4, byteorder='little'))
        #rel_count
        mu.mem_write(info_base+212, int(self.__rel_count).to_bytes(4, byteorder='little'))

        #preinit_array
        mu.mem_write(info_base+216, int(0).to_bytes(4, byteorder='little'))
        #preinit_array_count
        mu.mem_write(info_base+220, int(0).to_bytes(4, byteorder='little'))

        #init_array
        mu.mem_write(info_base+224, int(load_base+self.__init_array_off).to_bytes(4, byteorder='little'))
        #init_array_count
        mu.mem_write(info_base+228, int(self.__init_array_size/4).to_bytes(4, byteorder='little'))

        #finit_array
        mu.mem_write(info_base+232, int(0).to_bytes(4, byteorder='little'))
        #finit_array_count
        mu.mem_write(info_base+236, int(0).to_bytes(4, byteorder='little'))

        #init_func
        mu.mem_write(info_base+240, int(load_base+self.__init_off).to_bytes(4, byteorder='little'))
        #fini_func
        mu.mem_write(info_base+244, int(0).to_bytes(4, byteorder='little'))

        #ARM_exidx
        mu.mem_write(info_base+248, int(0).to_bytes(4, byteorder='little'))
        #ARM_exidx_count
        mu.mem_write(info_base+252, int(0).to_bytes(4, byteorder='little'))

        #ref_count
        mu.mem_write(info_base+256, int(1).to_bytes(4, byteorder='little'))

        #link_map
        mu.mem_write(info_base+260, int(0).to_bytes(20, byteorder='little'))

        #constructors_called
        mu.mem_write(info_base+280, int(1).to_bytes(4, byteorder='little'))
        
        #Elf32_Addr load_bias
        mu.mem_write(info_base+284, int(0).to_bytes(4, byteorder='little'))
        
        soinfo_sz = 288
        return soinfo_sz
    #
#