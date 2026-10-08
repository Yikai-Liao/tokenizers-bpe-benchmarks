
.bench/builds/924e37e6749c5ac1dd80cf9ad0dde3c89c10404319fd77fbde1001dcc7ec0021/bpe-bench-runner:     file format elf64-x86-64


Disassembly of section .text:

0000000000143800 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get>:
  143800:	50                   	push   %rax
  143801:	89 f1                	mov    %esi,%ecx
  143803:	81 fe 80 00 00 00    	cmp    $0x80,%esi
  143809:	73 06                	jae    143811 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x11>
  14380b:	8b 44 8f 70          	mov    0x70(%rdi,%rcx,4),%eax
  14380f:	59                   	pop    %rcx
  143810:	c3                   	ret
  143811:	81 fe 00 00 01 00    	cmp    $0x10000,%esi
  143817:	0f 83 b9 00 00 00    	jae    1438d6 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0xd6>
  14381d:	89 c8                	mov    %ecx,%eax
  14381f:	c1 e8 06             	shr    $0x6,%eax
  143822:	48 8b 77 08          	mov    0x8(%rdi),%rsi
  143826:	48 39 f0             	cmp    %rsi,%rax
  143829:	0f 83 79 01 00 00    	jae    1439a8 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x1a8>
  14382f:	83 e1 3f             	and    $0x3f,%ecx
  143832:	48 8b 17             	mov    (%rdi),%rdx
  143835:	48 8b 14 c2          	mov    (%rdx,%rax,8),%rdx
  143839:	48 0f a3 ca          	bt     %rcx,%rdx
  14383d:	0f 83 5e 01 00 00    	jae    1439a1 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x1a1>
  143843:	48 8b 77 18          	mov    0x18(%rdi),%rsi
  143847:	48 39 f0             	cmp    %rsi,%rax
  14384a:	0f 83 67 01 00 00    	jae    1439b7 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x1b7>
  143850:	48 c7 c6 ff ff ff ff 	mov    $0xffffffffffffffff,%rsi
  143857:	48 d3 e6             	shl    %cl,%rsi
  14385a:	48 f7 d6             	not    %rsi
  14385d:	48 21 f2             	and    %rsi,%rdx
  143860:	48 89 d1             	mov    %rdx,%rcx
  143863:	48 d1 e9             	shr    $1,%rcx
  143866:	48 be 55 55 55 55 55 	movabs $0x1555555555555555,%rsi
  14386d:	55 55 15 
  143870:	48 21 ce             	and    %rcx,%rsi
  143873:	48 29 f2             	sub    %rsi,%rdx
  143876:	48 b9 33 33 33 33 33 	movabs $0x3333333333333333,%rcx
  14387d:	33 33 33 
  143880:	48 89 d6             	mov    %rdx,%rsi
  143883:	48 21 ce             	and    %rcx,%rsi
  143886:	48 c1 ea 02          	shr    $0x2,%rdx
  14388a:	48 21 ca             	and    %rcx,%rdx
  14388d:	48 01 f2             	add    %rsi,%rdx
  143890:	48 89 d1             	mov    %rdx,%rcx
  143893:	48 c1 e9 04          	shr    $0x4,%rcx
  143897:	48 01 d1             	add    %rdx,%rcx
  14389a:	48 ba 0f 0f 0f 0f 0f 	movabs $0xf0f0f0f0f0f0f0f,%rdx
  1438a1:	0f 0f 0f 
  1438a4:	48 21 ca             	and    %rcx,%rdx
  1438a7:	48 b9 01 01 01 01 01 	movabs $0x101010101010101,%rcx
  1438ae:	01 01 01 
  1438b1:	48 0f af ca          	imul   %rdx,%rcx
  1438b5:	48 c1 e9 38          	shr    $0x38,%rcx
  1438b9:	48 8b 57 10          	mov    0x10(%rdi),%rdx
  1438bd:	48 8b 77 28          	mov    0x28(%rdi),%rsi
  1438c1:	03 0c 82             	add    (%rdx,%rax,4),%ecx
  1438c4:	48 39 ce             	cmp    %rcx,%rsi
  1438c7:	0f 86 f9 00 00 00    	jbe    1439c6 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x1c6>
  1438cd:	48 8b 47 20          	mov    0x20(%rdi),%rax
  1438d1:	8b 04 88             	mov    (%rax,%rcx,4),%eax
  1438d4:	59                   	pop    %rcx
  1438d5:	c3                   	ret
  1438d6:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
  1438db:	48 83 7f 48 00       	cmpq   $0x0,0x48(%rdi)
  1438e0:	0f 84 b9 00 00 00    	je     14399f <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x19f>
  1438e6:	48 33 4f 58          	xor    0x58(%rdi),%rcx
  1438ea:	48 ba 2d 7f 95 4c 2d 	movabs $0x5851f42d4c957f2d,%rdx
  1438f1:	f4 51 58 
  1438f4:	48 89 c8             	mov    %rcx,%rax
  1438f7:	48 f7 e2             	mul    %rdx
  1438fa:	48 89 c1             	mov    %rax,%rcx
  1438fd:	48 31 d1             	xor    %rdx,%rcx
  143900:	48 89 c8             	mov    %rcx,%rax
  143903:	48 f7 67 50          	mulq   0x50(%rdi)
  143907:	48 31 c2             	xor    %rax,%rdx
  14390a:	48 d3 c2             	rol    %cl,%rdx
  14390d:	48 89 d0             	mov    %rdx,%rax
  143910:	48 c1 e8 39          	shr    $0x39,%rax
  143914:	48 8b 4f 30          	mov    0x30(%rdi),%rcx
  143918:	48 8b 7f 38          	mov    0x38(%rdi),%rdi
  14391c:	66 0f 6e c0          	movd   %eax,%xmm0
  143920:	66 0f 60 c0          	punpcklbw %xmm0,%xmm0
  143924:	f2 0f 70 c0 00       	pshuflw $0x0,%xmm0,%xmm0
  143929:	66 0f 70 c0 44       	pshufd $0x44,%xmm0,%xmm0
  14392e:	45 31 c0             	xor    %r8d,%r8d
  143931:	66 0f 76 c9          	pcmpeqd %xmm1,%xmm1
  143935:	48 21 fa             	and    %rdi,%rdx
  143938:	f3 0f 6f 14 11       	movdqu (%rcx,%rdx,1),%xmm2
  14393d:	66 0f 6f da          	movdqa %xmm2,%xmm3
  143941:	66 0f 74 d8          	pcmpeqb %xmm0,%xmm3
  143945:	66 0f d7 c3          	pmovmskb %xmm3,%eax
  143949:	85 c0                	test   %eax,%eax
  14394b:	74 2c                	je     143979 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x179>
  14394d:	f3 44 0f bc c8       	tzcnt  %eax,%r9d
  143952:	49 01 d1             	add    %rdx,%r9
  143955:	49 21 f9             	and    %rdi,%r9
  143958:	4e 8d 14 cd 00 00 00 	lea    0x0(,%r9,8),%r10
  14395f:	00 
  143960:	49 89 cb             	mov    %rcx,%r11
  143963:	4d 29 d3             	sub    %r10,%r11
  143966:	41 3b 73 f8          	cmp    -0x8(%r11),%esi
  14396a:	74 2b                	je     143997 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x197>
  14396c:	44 8d 48 ff          	lea    -0x1(%rax),%r9d
  143970:	66 41 21 c1          	and    %ax,%r9w
  143974:	44 89 c8             	mov    %r9d,%eax
  143977:	75 d4                	jne    14394d <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x14d>
  143979:	66 0f 74 d1          	pcmpeqb %xmm1,%xmm2
  14397d:	66 0f d7 c2          	pmovmskb %xmm2,%eax
  143981:	85 c0                	test   %eax,%eax
  143983:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
  143988:	75 15                	jne    14399f <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x19f>
  14398a:	4c 01 c2             	add    %r8,%rdx
  14398d:	48 83 c2 10          	add    $0x10,%rdx
  143991:	49 83 c0 10          	add    $0x10,%r8
  143995:	eb 9e                	jmp    143935 <_RNvMNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine10vocabularyNtB2_12CharacterIds3get+0x135>
  143997:	49 f7 d9             	neg    %r9
  14399a:	42 8b 44 c9 fc       	mov    -0x4(%rcx,%r9,8),%eax
  14399f:	59                   	pop    %rcx
  1439a0:	c3                   	ret
  1439a1:	b8 ff ff ff ff       	mov    $0xffffffff,%eax
  1439a6:	59                   	pop    %rcx
  1439a7:	c3                   	ret
  1439a8:	48 8d 15 61 57 06 00 	lea    0x65761(%rip),%rdx        # 1a9110 <_RNvNtNtCsiBRsgNtTiOm_9bitcannon8classify11atom_tables11ATOM_TABLES+0x42d0>
  1439af:	48 89 c7             	mov    %rax,%rdi
  1439b2:	e8 84 54 f4 ff       	call   88e3b <_RNvNtCsgxBkk5gSRhY_4core9panicking18panic_bounds_check>
  1439b7:	48 8d 15 6a 57 06 00 	lea    0x6576a(%rip),%rdx        # 1a9128 <_RNvNtNtCsiBRsgNtTiOm_9bitcannon8classify11atom_tables11ATOM_TABLES+0x42e8>
  1439be:	48 89 c7             	mov    %rax,%rdi
  1439c1:	e8 75 54 f4 ff       	call   88e3b <_RNvNtCsgxBkk5gSRhY_4core9panicking18panic_bounds_check>
  1439c6:	48 8d 15 73 57 06 00 	lea    0x65773(%rip),%rdx        # 1a9140 <_RNvNtNtCsiBRsgNtTiOm_9bitcannon8classify11atom_tables11ATOM_TABLES+0x4300>
  1439cd:	48 89 cf             	mov    %rcx,%rdi
  1439d0:	e8 66 54 f4 ff       	call   88e3b <_RNvNtCsgxBkk5gSRhY_4core9panicking18panic_bounds_check>
  1439d5:	cc                   	int3
  1439d6:	cc                   	int3
  1439d7:	cc                   	int3
  1439d8:	cc                   	int3
  1439d9:	cc                   	int3
  1439da:	cc                   	int3
  1439db:	cc                   	int3
  1439dc:	cc                   	int3
  1439dd:	cc                   	int3
  1439de:	cc                   	int3
  1439df:	cc                   	int3

00000000001439e0 <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_>:
  1439e0:	55                   	push   %rbp
  1439e1:	41 57                	push   %r15
  1439e3:	41 56                	push   %r14
  1439e5:	41 55                	push   %r13
  1439e7:	41 54                	push   %r12
  1439e9:	53                   	push   %rbx
  1439ea:	48 81 ec e8 00 00 00 	sub    $0xe8,%rsp
  1439f1:	89 54 24 0c          	mov    %edx,0xc(%rsp)
  1439f5:	48 89 f3             	mov    %rsi,%rbx
  1439f8:	49 89 ff             	mov    %rdi,%r15
  1439fb:	0f 10 07             	movups (%rdi),%xmm0
  1439fe:	0f 10 4f 10          	movups 0x10(%rdi),%xmm1
  143a02:	0f 10 57 20          	movups 0x20(%rdi),%xmm2
  143a06:	0f 29 54 24 30       	movaps %xmm2,0x30(%rsp)
  143a0b:	0f 29 4c 24 20       	movaps %xmm1,0x20(%rsp)
  143a10:	0f 29 44 24 10       	movaps %xmm0,0x10(%rsp)
  143a15:	48 8d 86 10 01 00 00 	lea    0x110(%rsi),%rax
  143a1c:	48 8b 8e 00 01 00 00 	mov    0x100(%rsi),%rcx
  143a23:	48 89 44 24 58       	mov    %rax,0x58(%rsp)
  143a28:	48 c7 44 24 60 00 00 	movq   $0x0,0x60(%rsp)
  143a2f:	00 00 
  143a31:	48 89 4c 24 68       	mov    %rcx,0x68(%rsp)
  143a36:	c6 44 24 70 00       	movb   $0x0,0x70(%rsp)
  143a3b:	48 c7 44 24 40 00 00 	movq   $0x0,0x40(%rsp)
  143a42:	00 00 
  143a44:	48 8b 86 18 01 00 00 	mov    0x118(%rsi),%rax
  143a4b:	4c 8b a0 08 01 00 00 	mov    0x108(%rax),%r12
  143a52:	4c 8b b0 00 01 00 00 	mov    0x100(%rax),%r14
  143a59:	48 8b 86 18 01 00 00 	mov    0x118(%rsi),%rax
  143a60:	48 8b a8 08 01 00 00 	mov    0x108(%rax),%rbp
  143a67:	48 8b 80 00 01 00 00 	mov    0x100(%rax),%rax
  143a6e:	48 8b b6 28 01 00 00 	mov    0x128(%rsi),%rsi
  143a75:	48 89 e9             	mov    %rbp,%rcx
  143a78:	48 29 c1             	sub    %rax,%rcx
  143a7b:	48 39 f1             	cmp    %rsi,%rcx
  143a7e:	0f 8d 48 02 00 00    	jge    143ccc <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x2ec>
  143a84:	4d 29 f4             	sub    %r14,%r12
  143a87:	48 b9 00 00 00 00 01 	movabs $0x100000000,%rcx
  143a8e:	00 00 00 
  143a91:	48 8b 83 20 01 00 00 	mov    0x120(%rbx),%rax
  143a98:	48 ff ce             	dec    %rsi
  143a9b:	48 21 ee             	and    %rbp,%rsi
  143a9e:	48 c1 e6 04          	shl    $0x4,%rsi
  143aa2:	4c 8d 2d 47 09 00 00 	lea    0x947(%rip),%r13        # 1443f0 <_RNvXs2_NtCshzb3JJWXSZS_10rayon_core3jobINtB5_8StackJobNtNtB7_5latch9SpinLatchNCINvNvNtB7_4join12join_context6call_buNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB21_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB3M_4sync6atomic6AtomichEj3_EEEINtNtB1Z_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB5V_10CorpusPlan11fill_tokensB4A_NCNvXs1_NtB5X_5slotsNtB7I_14PackedU24SlotsNtB7I_11SlotStorage13from_prepared0Es3_0EEs_0E0uENtB5_3Job7executeB65_>
  143aa9:	4c 89 2c 30          	mov    %r13,(%rax,%rsi,1)
  143aad:	4c 8d 74 24 10       	lea    0x10(%rsp),%r14
  143ab2:	4c 89 74 30 08       	mov    %r14,0x8(%rax,%rsi,1)
  143ab7:	48 8b 83 18 01 00 00 	mov    0x118(%rbx),%rax
  143abe:	48 ff c5             	inc    %rbp
  143ac1:	48 89 a8 08 01 00 00 	mov    %rbp,0x108(%rax)
  143ac8:	48 8b b3 10 01 00 00 	mov    0x110(%rbx),%rsi
  143acf:	48 8d be d8 01 00 00 	lea    0x1d8(%rsi),%rdi
  143ad6:	66 2e 0f 1f 84 00 00 	cs nopw 0x0(%rax,%rax,1)
  143add:	00 00 00 
  143ae0:	48 8b 86 f0 01 00 00 	mov    0x1f0(%rsi),%rax
  143ae7:	48 85 c8             	test   %rcx,%rax
  143aea:	75 1e                	jne    143b0a <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x12a>
  143aec:	48 89 c2             	mov    %rax,%rdx
  143aef:	48 09 ca             	or     %rcx,%rdx
  143af2:	f0 48 0f b1 96 f0 01 	lock cmpxchg %rdx,0x1f0(%rsi)
  143af9:	00 00 
  143afb:	75 e3                	jne    143ae0 <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x100>
  143afd:	48 89 d0             	mov    %rdx,%rax
  143b00:	48 25 ff ff 00 00    	and    $0xffff,%rax
  143b06:	75 10                	jne    143b18 <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x138>
  143b08:	eb 22                	jmp    143b2c <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x14c>
  143b0a:	48 89 c2             	mov    %rax,%rdx
  143b0d:	48 89 d0             	mov    %rdx,%rax
  143b10:	48 25 ff ff 00 00    	and    $0xffff,%rax
  143b16:	74 14                	je     143b2c <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x14c>
  143b18:	4d 85 e4             	test   %r12,%r12
  143b1b:	0f 8f 9c 01 00 00    	jg     143cbd <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x2dd>
  143b21:	c1 ea 10             	shr    $0x10,%edx
  143b24:	39 c2                	cmp    %eax,%edx
  143b26:	0f 84 91 01 00 00    	je     143cbd <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x2dd>
  143b2c:	49 8b 47 30          	mov    0x30(%r15),%rax
  143b30:	49 8b 4f 38          	mov    0x38(%r15),%rcx
  143b34:	4d 8b 47 40          	mov    0x40(%r15),%r8
  143b38:	4d 8b 4f 48          	mov    0x48(%r15),%r9
  143b3c:	49 8b 77 50          	mov    0x50(%r15),%rsi
  143b40:	48 8b 38             	mov    (%rax),%rdi
  143b43:	48 8b 11             	mov    (%rcx),%rdx
  143b46:	48 8b 49 08          	mov    0x8(%rcx),%rcx
  143b4a:	48 89 34 24          	mov    %rsi,(%rsp)
  143b4e:	0f b6 6c 24 0c       	movzbl 0xc(%rsp),%ebp
  143b53:	89 ee                	mov    %ebp,%esi
  143b55:	e8 66 eb ff ff       	call   1426c0 <_RINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB8_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB1S_4sync6atomic6AtomichEj3_EEEINtNtB6_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB40_10CorpusPlan11fill_tokensB2G_NCNvXs1_NtB42_5slotsNtB5N_14PackedU24SlotsNtB5N_11SlotStorage13from_prepared0Es3_0EEB4a_>
  143b5a:	66 0f 1f 44 00 00    	nopw   0x0(%rax,%rax,1)
  143b60:	48 8b 44 24 60       	mov    0x60(%rsp),%rax
  143b65:	48 83 f8 03          	cmp    $0x3,%rax
  143b69:	74 34                	je     143b9f <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x1bf>
  143b6b:	48 89 df             	mov    %rbx,%rdi
  143b6e:	e8 7d 44 fa ff       	call   e7ff0 <_RNvMs8_NtCshzb3JJWXSZS_10rayon_core8registryNtB5_12WorkerThread14take_local_job.1399>
  143b73:	48 85 c0             	test   %rax,%rax
  143b76:	74 18                	je     143b90 <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x1b0>
  143b78:	4c 89 f1             	mov    %r14,%rcx
  143b7b:	48 31 d1             	xor    %rdx,%rcx
  143b7e:	48 89 c6             	mov    %rax,%rsi
  143b81:	4c 31 ee             	xor    %r13,%rsi
  143b84:	48 09 ce             	or     %rcx,%rsi
  143b87:	74 3e                	je     143bc7 <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x1e7>
  143b89:	48 89 d7             	mov    %rdx,%rdi
  143b8c:	ff d0                	call   *%rax
  143b8e:	eb d0                	jmp    143b60 <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x180>
  143b90:	48 8b 44 24 60       	mov    0x60(%rsp),%rax
  143b95:	48 83 f8 03          	cmp    $0x3,%rax
  143b99:	0f 85 60 01 00 00    	jne    143cff <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x31f>
  143b9f:	48 8b 44 24 40       	mov    0x40(%rsp),%rax
  143ba4:	48 83 f8 01          	cmp    $0x1,%rax
  143ba8:	0f 84 fd 00 00 00    	je     143cab <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x2cb>
  143bae:	48 83 f8 02          	cmp    $0x2,%rax
  143bb2:	0f 85 2f 01 00 00    	jne    143ce7 <_RNCINvNtCshzb3JJWXSZS_10rayon_core4join12join_contextNCINvNvNtNtCskOCPxHELzib_5rayon4iter8plumbing24bridge_producer_consumer6helperINtNtB10_3vec13DrainProducerTjjjbQSINtNtNtCsgxBkk5gSRhY_4core3mem12maybe_uninit11MaybeUninitAINtNtNtB2L_4sync6atomic6AtomichEj3_EEEINtNtBY_8for_each15ForEachConsumerNCINvMs0_NtNtNtNtNtCs9wdF9wCwNM0_8tk_train8trainers3bpe6engine6corpus7prepareNtB4T_10CorpusPlan11fill_tokensB3z_NCNvXs1_NtB4V_5slotsNtB6G_14PackedU24SlotsNtB6G_11SlotStorage13from_prepared0Es3_0EE0NCBR_s_0uuE0B53_+0x307>
  143bb8:	48 8b 7c 24 48       	mov    0x48(%rsp),%rdi
  143bbd:	48 8b 74 24 50       	mov    0x50(%rsp),%rsi
  143bc2:	e8 29 41 f5 ff       	call   97cf0 <_RNvNtCshzb3JJWXSZS_10rayon_core6unwind16resume_unwinding>
  143bc7:	0f 28 44 24 10       	movaps 0x10(%rsp),%xmm0
  143bcc:	0f 28 4c 24 20       	movaps 0x20(%rsp),%xmm1
  143bd1:	0f 28 54 24 30       	movaps 0x30(%rsp),%xmm2
  143bd6:	0f 28 5c 24 40       	movaps 0x40(%rsp),%xmm3
  143bdb:	0f 29 84 24 80 00 00 	movaps %xmm0,0x80(%rsp)
  143be2:	00 
  143be3:	48 8b 44 24 70       	mov    0x70(%rsp),%rax
  143be8:	48 89 84 24 e0 00 00 	mov    %rax,0xe0(%rsp)
  143bef:	00 
  143bf0:	0f 28 44 24 60       	movaps 0x60(%rsp),%xmm0
  143bf5:	0f 29 84 24 d0 00 00 	movaps %xmm0,0xd0(%rsp)
  143bfc:	00 
  143bfd:	0f 28 44 24 50       	movaps 0x50(%rsp),%xmm0
  143c02:	0f 29 84 24 c0 00 00 	movaps %xmm0,0xc0(%rsp)
  143c09:	00 
  143c0a:	0f 29 9c 24 b0 00 00 	movaps %xmm3,0xb0(%rsp)
  143c11:	00 
  143c12:	0f 29 94 24 a0 00 00 	movaps %xmm2,0xa0(%rsp)
  143c19:	00 
  143c1a:	0f                   	.byte 0xf
  143c1b:	29                   	.byte 0x29
  143c1c:	8c 24 90             	mov    %fs,(%rax,%rdx,4)
	...
