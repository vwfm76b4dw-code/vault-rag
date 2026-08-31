#include <bits/stdc++.h>
#include <conio.h>
using namespace std;
int n;
bool is(int n){
	for(int i=2;i*i<=n;i++){
		if(n%i==0)return false;
	}
	return true;
}
int f(int n){
	for(int i=2;i<n;i++){
		if(is(i)&&n%i==0)return i;
	}
	return n;
}
int main()
{
	cin>>n;
	cout<<n<<"=";
	while(n){
		int s=f(n);
		if(s!=1){
			if(n/s==1){
				cout<<s<<endl;
				cout<<"按任意键继续...";
    			_getch();  // 等待用户按下任意键 
				return 0;
			}
			cout<<s<<"*";
			n/=s;
		}else break;
	}
}
