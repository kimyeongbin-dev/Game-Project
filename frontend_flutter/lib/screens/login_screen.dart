import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nicknameController = TextEditingController();
  final _passwordController = TextEditingController();

  bool _isRegisterMode = false;
  bool _obscurePassword = true;
  String? _nicknameError;
  String? _passwordError;

  @override
  void dispose() {
    _nicknameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    final authService = context.read<AuthService>();
    final nickname = _nicknameController.text.trim();
    final password = _passwordController.text;

    setState(() {
      _nicknameError = null;
      _passwordError = null;
    });

    final result = _isRegisterMode
        ? await authService.register(nickname, password)
        : await authService.login(nickname, password);

    if (!mounted) return;

    if (result.success) {
      // 로그인 성공 시 자동으로 홈으로 이동 (main.dart에서 처리)
      if (result.resetInfo != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('다음 랭킹 리셋: ${result.resetInfo!.timeRemaining}'),
            duration: const Duration(seconds: 3),
          ),
        );
      }
    } else {
      // 에러 처리
      setState(() {
        if (result.error == 'nickname_exists' ||
            result.error == 'nickname_not_found') {
          _nicknameError = result.message;
        } else if (result.error == 'wrong_password') {
          _passwordError = result.message;
        } else {
          // 일반 에러는 스낵바로
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(result.message),
              backgroundColor: Colors.red,
            ),
          );
        }
      });
    }
  }

  String? _validateNickname(String? value) {
    if (value == null || value.trim().isEmpty) {
      return '닉네임을 입력하세요';
    }
    if (value.trim().length < 2) {
      return '닉네임은 2자 이상이어야 합니다';
    }
    if (value.trim().length > 20) {
      return '닉네임은 20자 이하여야 합니다';
    }
    if (!RegExp(r'^[a-zA-Z0-9가-힣_]+$').hasMatch(value.trim())) {
      return '한글, 영문, 숫자, 언더스코어만 사용 가능';
    }
    return null;
  }

  String? _validatePassword(String? value) {
    if (value == null || value.isEmpty) {
      return '비밀번호를 입력하세요';
    }
    if (_isRegisterMode && value.length < 4) {
      return '비밀번호는 4자 이상이어야 합니다';
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final authService = context.watch<AuthService>();
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // 로고 영역
                    Icon(
                      Icons.sports_esports,
                      size: 80,
                      color: colorScheme.primary,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'Game Hub',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 32,
                        fontWeight: FontWeight.bold,
                        color: colorScheme.primary,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _isRegisterMode ? '새 계정 만들기' : '로그인',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 16,
                        color: colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 48),

                    // 닉네임 입력
                    TextFormField(
                      controller: _nicknameController,
                      decoration: InputDecoration(
                        labelText: '닉네임',
                        hintText: '2-20자 (한글/영문/숫자)',
                        prefixIcon: const Icon(Icons.person),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                        errorText: _nicknameError,
                      ),
                      textInputAction: TextInputAction.next,
                      validator: _validateNickname,
                      onChanged: (_) {
                        if (_nicknameError != null) {
                          setState(() => _nicknameError = null);
                        }
                      },
                    ),
                    const SizedBox(height: 16),

                    // 비밀번호 입력
                    TextFormField(
                      controller: _passwordController,
                      decoration: InputDecoration(
                        labelText: '비밀번호',
                        hintText: _isRegisterMode ? '4자 이상' : '',
                        prefixIcon: const Icon(Icons.lock),
                        suffixIcon: IconButton(
                          icon: Icon(
                            _obscurePassword
                                ? Icons.visibility_off
                                : Icons.visibility,
                          ),
                          onPressed: () {
                            setState(() => _obscurePassword = !_obscurePassword);
                          },
                        ),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                        errorText: _passwordError,
                      ),
                      obscureText: _obscurePassword,
                      textInputAction: TextInputAction.done,
                      validator: _validatePassword,
                      onFieldSubmitted: (_) => _submit(),
                      onChanged: (_) {
                        if (_passwordError != null) {
                          setState(() => _passwordError = null);
                        }
                      },
                    ),
                    const SizedBox(height: 24),

                    // 제출 버튼
                    FilledButton(
                      onPressed: authService.isLoading ? null : _submit,
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: authService.isLoading
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : Text(
                              _isRegisterMode ? '가입하기' : '로그인',
                              style: const TextStyle(fontSize: 16),
                            ),
                    ),
                    const SizedBox(height: 16),

                    // 모드 전환 버튼
                    TextButton(
                      onPressed: () {
                        setState(() {
                          _isRegisterMode = !_isRegisterMode;
                          _nicknameError = null;
                          _passwordError = null;
                        });
                      },
                      child: Text(
                        _isRegisterMode
                            ? '이미 계정이 있나요? 로그인'
                            : '계정이 없나요? 가입하기',
                      ),
                    ),

                    const SizedBox(height: 32),

                    // 게스트 모드 안내
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: colorScheme.surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Column(
                        children: [
                          Row(
                            children: [
                              Icon(
                                Icons.info_outline,
                                size: 20,
                                color: colorScheme.primary,
                              ),
                              const SizedBox(width: 8),
                              Text(
                                '안내',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  color: colorScheme.primary,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 8),
                          Text(
                            '로그인하면 랭킹전, 친구 대전을 즐길 수 있습니다.\n'
                            '매일 오전 9시(KST)에 랭킹이 초기화됩니다.',
                            style: TextStyle(
                              fontSize: 13,
                              color: colorScheme.onSurfaceVariant,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
